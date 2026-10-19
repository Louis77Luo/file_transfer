"""Private, single-account clipboard and file storage."""
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash

DATA = Path(os.environ.get("DATA_DIR", "/data"))
FILES = DATA / "files"
FILES.mkdir(parents=True, exist_ok=True)
DB = DATA / "index.sqlite3"
QUOTA = int(os.environ.get("STORAGE_QUOTA_BYTES", 20 * 1024**3))
USERNAME = os.environ.get("APP_USERNAME", "leader")
PASSWORD_HASH = os.environ.get("APP_PASSWORD_HASH", "")
ORIGIN = os.environ.get("PUBLIC_ORIGIN", "https://file.louis77.top").rstrip("/")
COOKIE = "__Host-transfer_session"
SESSION_AGE = 14 * 86400
TEXT_LIMIT = 1024 * 1024
lock = threading.RLock()

if not PASSWORD_HASH:
    raise RuntimeError("APP_PASSWORD_HASH must be configured")

app = Flask(__name__, static_folder="static", static_url_path="/assets")
app.config.update(MAX_CONTENT_LENGTH=QUOTA, MAX_FORM_MEMORY_SIZE=TEXT_LIMIT)


@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


with connect() as db:
    db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
            size INTEGER NOT NULL, created_at INTEGER NOT NULL,
            preview TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts (ip TEXT PRIMARY KEY, count INTEGER NOT NULL, started INTEGER NOT NULL);
    """)

# Gunicorn runs one process with multiple threads. Incomplete files never count as saved items.
for partial in FILES.glob("*.part"):
    partial.unlink(missing_ok=True)
with connect() as db:
    known = {row[0] for row in db.execute("SELECT id FROM items")}
for orphan in FILES.iterdir():
    if orphan.is_file() and orphan.name not in known:
        orphan.unlink(missing_ok=True)
reserved = 0


def failure(message, status=400):
    return jsonify(error=message), status


def session_key():
    return hashlib.sha256(request.cookies.get(COOKIE, "").encode()).hexdigest()


def usage(db):
    return db.execute("SELECT COALESCE(SUM(size), 0) FROM items").fetchone()[0]


@app.before_request
def protect():
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("Origin") != ORIGIN or request.headers.get("X-Requested-With") != "FileTransfer":
            return failure("请求来源无效，请刷新页面后重试。", 403)
    if request.path.startswith("/api/") and request.path != "/api/login":
        with connect() as db:
            valid = db.execute("SELECT 1 FROM sessions WHERE token=? AND expires>?", (session_key(), int(time.time()))).fetchone()
        if not valid:
            return failure("请先登录。", 401)


@app.after_request
def security_headers(response):
    response.headers.update({
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "same-origin",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        "Cache-Control": "no-store",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    })
    return response


@app.errorhandler(Exception)
def errors(error):
    if isinstance(error, HTTPException):
        messages = {404: "内容不存在或已被删除。", 413: "内容超过可用存储空间或大小限制。", 405: "不支持的请求方式。"}
        return failure(messages.get(error.code, "请求无法完成。"), error.code)
    if isinstance(error, OSError) and error.errno == 28:
        return failure("服务器磁盘空间不足，请删除一些内容后重试。", 507)
    app.logger.exception("Request failed")
    return failure("服务器暂时无法完成请求，请稍后重试。", 500)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/healthz")
def health():
    with connect() as db:
        db.execute("SELECT 1").fetchone()
    return jsonify(status="ok")


@app.post("/api/login")
def login():
    if request.content_length is None or request.content_length > 4096:
        return failure("登录请求无效。", 400)
    body = request.get_json(silent=True) or {}
    username, password = body.get("username", ""), body.get("password", "")
    if not isinstance(username, str) or not isinstance(password, str):
        return failure("请输入用户名和密码。", 400)
    ip = request.headers.get("X-Real-IP", request.remote_addr)[:100]
    now = int(time.time())
    with lock, connect() as db:
        db.execute("DELETE FROM attempts WHERE started<?", (now - 600,))
        row = db.execute("SELECT count FROM attempts WHERE ip=?", (ip,)).fetchone()
        if row and row[0] >= 10:
            return failure("尝试次数过多，请 10 分钟后重试。", 429)
        valid_password = check_password_hash(PASSWORD_HASH, password)
        if not (hmac.compare_digest(username.encode(), USERNAME.encode()) and valid_password):
            db.execute("INSERT INTO attempts VALUES (?,1,?) ON CONFLICT(ip) DO UPDATE SET count=count+1", (ip, now))
            return failure("用户名或密码不正确。", 401)
        db.execute("DELETE FROM attempts WHERE ip=?", (ip,))
        db.execute("DELETE FROM sessions WHERE expires<?", (now,))
        token = secrets.token_urlsafe(32)
        db.execute("INSERT INTO sessions VALUES (?,?)", (hashlib.sha256(token.encode()).hexdigest(), now + SESSION_AGE))
    response = jsonify(username=USERNAME)
    response.set_cookie(COOKIE, token, max_age=SESSION_AGE, secure=True, httponly=True, samesite="Lax", path="/")
    return response


@app.post("/api/logout")
def logout():
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE token=?", (session_key(),))
    response = jsonify(ok=True)
    response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="Lax", path="/")
    return response


@app.get("/api/items")
def items():
    with connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM items ORDER BY created_at DESC, rowid DESC")]
        return jsonify(items=rows, used=usage(db), quota=QUOTA, username=USERNAME)


def save_stream(stream, size, kind, name, preview=""):
    global reserved
    if size is None or size < 0:
        return failure("无法确定文件大小，请重新选择文件。", 411)
    identifier = uuid.uuid4().hex
    partial, final = FILES / (identifier + ".part"), FILES / identifier
    with lock, connect() as db:
        if usage(db) + reserved + size > QUOTA:
            return failure("剩余空间不足，请删除一些内容后重试。", 413)
        # Leave room for the OS, database and the other services on the same disk.
        disk = os.statvfs(DATA)
        if disk.f_bavail * disk.f_frsize - reserved - size < 1024**3:
            return failure("服务器可用空间不足，请删除一些内容后重试。", 507)
        reserved += size
    try:
        remaining = size
        with partial.open("xb") as output:
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    return failure("上传未完成，请重新上传。", 400)
                output.write(chunk)
                remaining -= len(chunk)
            output.flush()
            os.fsync(output.fileno())
        with lock, connect() as db:
            partial.replace(final)
            db.execute("INSERT INTO items VALUES (?,?,?,?,?,?)", (identifier, kind, name, size, int(time.time()), preview))
        return jsonify(id=identifier), 201
    finally:
        with lock:
            reserved -= size
        partial.unlink(missing_ok=True)
        with connect() as db:
            saved = db.execute("SELECT 1 FROM items WHERE id=?", (identifier,)).fetchone()
        if not saved:
            final.unlink(missing_ok=True)


@app.post("/api/text")
def create_text():
    import io
    if request.content_length is None or request.content_length > TEXT_LIMIT + 8192:
        return failure("单条文本最多支持 1MB。", 413)
    body = request.get_json(silent=True) or {}
    text, title = body.get("text", ""), body.get("title", "")
    if not isinstance(text, str) or not isinstance(title, str) or not text.strip():
        return failure("请输入要传输的文本。")
    encoded = text.encode("utf-8")
    if len(encoded) > TEXT_LIMIT:
        return failure("单条文本最多支持 1MB。", 413)
    title = "".join(c for c in title if ord(c) >= 32 and ord(c) != 127).strip()[:120]
    title = title or text.strip().splitlines()[0][:60]
    return save_stream(io.BytesIO(encoded), len(encoded), "text", title, text[:280])


@app.post("/api/files")
def create_file():
    name = request.args.get("name", "").replace("\\", "/").split("/")[-1]
    name = "".join(c for c in name if ord(c) >= 32 and ord(c) != 127).strip()[:240]
    if not name or name in {".", ".."}:
        return failure("文件名无效。")
    return save_stream(request.stream, request.content_length, "file", name)


def item_by_id(identifier):
    with connect() as db:
        return db.execute("SELECT * FROM items WHERE id=?", (identifier,)).fetchone()


@app.get("/api/items/<identifier>/text")
def text_content(identifier):
    row = item_by_id(identifier)
    if not row or row["kind"] != "text":
        return failure("文本不存在。", 404)
    return jsonify(text=(FILES / identifier).read_text(encoding="utf-8"))


@app.get("/api/items/<identifier>/download")
def download(identifier):
    row = item_by_id(identifier)
    if not row:
        return failure("内容不存在。", 404)
    name = row["name"] + (".txt" if row["kind"] == "text" else "")
    return send_file(FILES / identifier, mimetype="application/octet-stream", as_attachment=True, download_name=name, conditional=True)


@app.delete("/api/items/<identifier>")
def delete(identifier):
    with lock, connect() as db:
        row = db.execute("SELECT id FROM items WHERE id=?", (identifier,)).fetchone()
        if not row:
            return failure("内容不存在。", 404)
        (FILES / identifier).unlink(missing_ok=True)
        db.execute("DELETE FROM items WHERE id=?", (identifier,))
    return jsonify(ok=True)
