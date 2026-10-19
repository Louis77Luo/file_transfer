import io
import os
from pathlib import Path
import tempfile
import unittest

from werkzeug.security import generate_password_hash

storage = tempfile.TemporaryDirectory(dir=os.environ.get("DATA_DIR"))
os.environ.update(DATA_DIR=storage.name, APP_PASSWORD_HASH=generate_password_hash("test-password", method="pbkdf2:sha256:1000"), PUBLIC_ORIGIN="https://file.louis77.top")
import app as service


class TransferTest(unittest.TestCase):
    def setUp(self):
        self.client = service.app.test_client()
        service.QUOTA = 20 * 1024**3
        with service.connect() as db:
            for table in ("items", "sessions", "attempts"):
                db.execute(f"DELETE FROM {table}")
        for file in service.FILES.iterdir():
            file.unlink()

    def request(self, method, route, **kwargs):
        return self.client.open(route, method=method, base_url="https://file.louis77.top", headers={"Origin": "https://file.louis77.top", "X-Requested-With": "FileTransfer"}, **kwargs)

    def login(self):
        response = self.request("POST", "/api/login", json={"username": "leader", "password": "test-password"})
        self.assertEqual(response.status_code, 200)
        return response

    def test_authentication_cookie_logout_and_download_privacy(self):
        self.assertEqual(self.request("GET", "/api/items").status_code, 401)
        self.assertEqual(self.request("POST", "/api/login", json={"username": "leader", "password": "wrong"}).status_code, 401)
        cookie = self.login().headers["Set-Cookie"]
        for flag in ("Secure", "HttpOnly", "SameSite=Lax", "Path=/"):
            self.assertIn(flag, cookie)
        created = self.request("POST", "/api/text", json={"text": "私人文字"}).json
        outsider = service.app.test_client()
        self.assertEqual(outsider.get(f"/api/items/{created['id']}/download").status_code, 401)
        self.assertEqual(self.request("POST", "/api/logout").status_code, 200)
        self.assertEqual(self.request("GET", "/api/items").status_code, 401)

    def test_text_preserves_utf8_newlines_and_html_without_execution(self):
        self.login()
        content = '第一行\n<script>alert("xss")</script>\n🙂'
        result = self.request("POST", "/api/text", json={"title": "跨设备文本", "text": content})
        self.assertEqual(result.status_code, 201)
        identifier = result.json["id"]
        self.assertEqual(self.request("GET", f"/api/items/{identifier}/text").json["text"], content)
        download = self.request("GET", f"/api/items/{identifier}/download")
        self.assertEqual(download.data, content.encode())
        self.assertIn("attachment", download.headers["Content-Disposition"])
        self.assertEqual(download.mimetype, "application/octet-stream")
        download.close()
        self.assertEqual(self.request("GET", "/api/items").json["used"], len(content.encode()))

    def test_binary_upload_range_download_and_delete(self):
        self.login()
        content = bytes(range(256)) * 8192
        result = self.request("POST", "/api/files?name=%E6%B5%8B%E8%AF%95.bin", data=content, content_type="application/octet-stream")
        self.assertEqual(result.status_code, 201)
        identifier = result.json["id"]
        response = self.request("GET", f"/api/items/{identifier}/download")
        self.assertEqual(response.data, content)
        response.close()
        ranged = self.client.get(f"/api/items/{identifier}/download", base_url="https://file.louis77.top", headers={"Range": "bytes=100-199"})
        self.assertEqual(ranged.status_code, 206)
        self.assertEqual(ranged.data, content[100:200])
        ranged.close()
        self.assertEqual(self.request("DELETE", f"/api/items/{identifier}").status_code, 200)
        self.assertEqual(self.request("GET", "/api/items").json["used"], 0)
        self.assertFalse((service.FILES / identifier).exists())

    def test_quota_rejects_overflow_and_releases_after_delete(self):
        self.login()
        service.QUOTA = 16
        first = self.request("POST", "/api/files?name=first.bin", data=b"a" * 10)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(self.request("POST", "/api/files?name=second.bin", data=b"b" * 7).status_code, 413)
        self.assertEqual(self.request("GET", "/api/items").json["used"], 10)
        self.request("DELETE", f"/api/items/{first.json['id']}")
        self.assertEqual(self.request("POST", "/api/files?name=second.bin", data=b"b" * 16).status_code, 201)

    def test_cross_site_and_missing_csrf_header_are_rejected(self):
        self.login()
        for headers in ({"Origin": "https://attacker.example", "X-Requested-With": "FileTransfer"}, {"Origin": "https://file.louis77.top"}):
            result = self.client.post("/api/text", json={"text": "bad"}, base_url="https://file.louis77.top", headers=headers)
            self.assertEqual(result.status_code, 403)
        self.assertEqual(self.request("GET", "/api/items").json["items"], [])

    def test_login_rate_limit_and_no_registration(self):
        for _ in range(10):
            self.assertEqual(self.request("POST", "/api/login", json={"username": "leader", "password": "wrong"}).status_code, 401)
        self.assertEqual(self.request("POST", "/api/login", json={"username": "leader", "password": "test-password"}).status_code, 429)
        self.assertEqual(self.request("POST", "/api/register", json={}).status_code, 401)

    def test_failed_stream_cleans_up_and_does_not_consume_quota(self):
        self.login()
        with service.app.test_request_context():
            response, status = service.save_stream(io.BytesIO(b"short"), 100, "file", "broken.bin")
            self.assertEqual(status, 400)
        self.assertEqual(service.reserved, 0)
        self.assertEqual(list(service.FILES.iterdir()), [])
        self.assertEqual(self.request("GET", "/api/items").json["used"], 0)

    def test_concurrent_uploads_cannot_exceed_quota(self):
        self.login()
        import threading
        service.QUOTA = 10
        started, resume = threading.Event(), threading.Event()
        results = []
        class SlowStream:
            def read(self, length):
                started.set()
                resume.wait(timeout=5)
                return b"a" * length
        def upload():
            with service.app.test_request_context():
                results.append(service.save_stream(SlowStream(), 8, "file", "first.bin")[1])
        thread = threading.Thread(target=upload)
        thread.start()
        self.assertTrue(started.wait(timeout=5))
        try:
            with service.app.test_request_context():
                self.assertEqual(service.save_stream(io.BytesIO(b"bbb"), 3, "file", "second.bin")[1], 413)
        finally:
            resume.set()
            thread.join(timeout=5)
        self.assertEqual(results, [201])
        self.assertEqual(service.reserved, 0)

    def test_file_paths_and_security_headers(self):
        self.login()
        response = self.request("POST", "/api/files?name=../../private.txt", data=b"safe")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.request("GET", "/api/items").json["items"][0]["name"], "private.txt")
        self.assertTrue((service.FILES / response.json["id"]).is_file())
        home = self.request("GET", "/")
        self.assertIn("frame-ancestors 'none'", home.headers["Content-Security-Policy"])
        self.assertEqual(home.headers["X-Content-Type-Options"], "nosniff")
        home.close()


if __name__ == "__main__":
    unittest.main()
