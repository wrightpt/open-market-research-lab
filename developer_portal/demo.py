"""Disposable loopback preview. Does not implement production authentication."""

import argparse
import json
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .catalog import datasets

ASSETS = {"/portal/": ("index.html", "text/html"),
          "/portal/app.js": ("app.js", "text/javascript"),
          "/portal/state.mjs": ("state.mjs", "text/javascript"),
          "/portal/style.css": ("style.css", "text/css")}
SCENARIOS = {"anonymous", "unrequested", "approved", "pending", "denied", "loading", "failure"}


class DemoServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=0):
        super().__init__(("127.0.0.1", port), DemoHandler)
        self.csrf = secrets.token_urlsafe(24)
        self.scenario = "anonymous"
        self.keys = []
        self.lock = threading.Lock()

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server_port}"

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        return connection, address


class DemoHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # No account, header, request-body, or once-only secret logging.

    def send(self, status, value, content_type="application/json"):
        payload = json.dumps(value, allow_nan=False).encode() if content_type == "application/json" else value
        self.send_response(status)
        for name, data in {
            "Content-Type": f"{content_type}; charset=utf-8", "Content-Length": str(len(payload)),
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        }.items():
            self.send_header(name, data)
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def error(self, status, code):
        self.send(status, {"error": {"code": code, "message": "Demo request rejected"}})

    def host_ok(self):
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def do_GET(self):
        if not self.host_ok():
            return self.error(403, "invalid_host")
        if self.path in ASSETS:
            filename, content_type = ASSETS[self.path]
            return self.send(200, (Path(__file__).parent / "static" / filename).read_bytes(), content_type)
        if self.path == "/portal/auth/github":
            return self.send(200, b'<!doctype html><html lang="en"><meta charset="utf-8"><title>Mock login only</title><h1>No GitHub login in this demo</h1><p>Return to the portal and choose an account scenario. No OAuth or real account access occurs.</p><a href="/portal/#account">Return to portal</a></html>', "text/html")
        if self.path == "/portal/api/session":
            scenario = self.server.scenario
            authenticated = scenario in {"unrequested", "approved", "pending", "denied"}
            return self.send(200, {"authenticated": authenticated,
                                  "user": {"id": "demo-user", "login": "fixture-researcher", "access_status": "none" if scenario == "unrequested" else scenario} if authenticated else None,
                                  "csrf_token": self.server.csrf, "mode": "demo"})
        if self.path not in {"/portal/api/datasets", "/portal/api/keys", "/portal/api/usage"}:
            return self.error(404, "not_found")
        if self.server.scenario == "failure":
            return self.error(503, "demo_failure")
        if self.server.scenario == "loading":
            time.sleep(2)
        if self.path == "/portal/api/datasets":
            return self.send(200, {"datasets": datasets()})
        if self.server.scenario != "approved":
            return self.error(403, "access_not_approved")
        if self.path == "/portal/api/keys":
            return self.send(200, {"keys": self.server.keys})
        self.send(200, {"limits": {"requests_per_day": 1000, "rows_per_request": 1000},
                        "usage": {"requests_today": 24, "rows_today": 384, "resets_at": "2026-10-17T00:00:00Z"}})

    def mutate(self):
        if not self.host_ok() or self.headers.get("Origin") != self.server.origin:
            return self.error(403, "origin_rejected")
        if not secrets.compare_digest(self.headers.get("X-CSRF-Token", "").encode(), self.server.csrf.encode()):
            return self.error(403, "csrf_rejected")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 4096 or self.headers.get("Transfer-Encoding"):
                return self.error(413, "body_limit")
            body = json.loads(self.rfile.read(length)) if length else {}
            if not isinstance(body, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            return self.error(400, "invalid_json")
        with self.server.lock:
            if self.path == "/portal/demo/scenario" and self.command == "POST":
                if not isinstance(body.get("scenario"), str) or body["scenario"] not in SCENARIOS:
                    return self.error(400, "invalid_scenario")
                self.server.scenario = body["scenario"]
                self.server.keys = []
                return self.send(200, {"mode": "demo"})
            if self.path == "/portal/api/logout" and self.command == "POST":
                self.server.scenario = "anonymous"
                return self.send(200, {"authenticated": False})
            if self.path == "/portal/api/access-requests" and self.command == "POST":
                if self.server.scenario != "unrequested":
                    return self.error(403, "demo_access_requests_unavailable")
                if not isinstance(body.get("purpose"), str) or not 20 <= len(body["purpose"]) <= 1000:
                    return self.error(400, "invalid_purpose")
                self.server.scenario = "pending"
                return self.send(202, {"access_status": "pending"})
            if self.server.scenario != "approved":
                return self.error(403, "access_not_approved")
            identifier = self.path.removeprefix("/portal/api/keys/").removesuffix("/rotate")
            current = next((key for key in self.server.keys if key["id"] == identifier), None)
            if self.command == "DELETE" and current and self.path == f"/portal/api/keys/{identifier}":
                current["revoked"] = True
                return self.send(200, {"revoked": True})
            if len(self.server.keys) >= 20:
                return self.error(429, "demo_key_limit")
            if self.command == "POST" and self.path.endswith("/rotate") and current and not current["revoked"]:
                current["revoked"] = True
                name = current["name"]
            elif self.command == "POST" and self.path == "/portal/api/keys":
                name = body.get("name")
                if (not isinstance(name, str) or not 3 <= len(name.strip()) <= 80
                    or body.get("scopes") != ["research:read"] or body.get("expires_in_days") != 30):
                    return self.error(400, "invalid_key_request")
            else:
                return self.error(404, "not_found")
            now = datetime.now(timezone.utc)
            key = {"id": secrets.token_hex(8), "name": name, "scopes": ["research:read"],
                   "created_at": now.isoformat(), "expires_at": (now + timedelta(days=30)).isoformat(), "revoked": False}
            self.server.keys.append(key)
            # Deliberately nonfunctional; never retained in the server key list.
            self.send(201, {"key": key, "secret": "DEMO_NOT_A_CREDENTIAL_" + secrets.token_hex(12)})

    do_POST = mutate
    do_DELETE = mutate


def main():
    parser = argparse.ArgumentParser(description="Loopback-only mock portal; no real GitHub login")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with DemoServer(args.port) as server:
        print(f"DEMO / MOCK ONLY: {server.origin}/portal/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
