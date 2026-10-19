"""Run on the host to create a private .env without storing plaintext passwords."""
from getpass import getpass
import hashlib
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parent.parent
target = root / ".env"
if target.exists():
    raise SystemExit(".env already exists; refusing to overwrite it.")
password = getpass("Account password (not saved as plaintext): ")
if not password:
    raise SystemExit("Password cannot be empty.")
salt = secrets.token_hex(16)
digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600000).hex()
password_hash = f"pbkdf2:sha256:600000${salt}${digest}"
content = f"APP_USERNAME=leader\nAPP_PASSWORD_HASH='{password_hash}'\nPUBLIC_ORIGIN=https://file.louis77.top\nSTORAGE_QUOTA_BYTES=21474836480\n"
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as output:
    output.write(content)
data = root / "data"
data.mkdir(mode=0o700, exist_ok=True)
os.chown(data, 10001, 10001)
print("Created private .env and data directory.")
