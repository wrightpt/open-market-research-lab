"""Fixed-origin loopback server. Local personas are not production identity."""

import json
import re
import secrets
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from market_lab.io import LabError, _check_tree, _unique_pairs

from .service import Commons, PERSONAS

ASSETS = {
    "/commons/": ("index.html", "text/html"),
    "/commons/app.js": ("app.js", "text/javascript"),
    "/commons/style.css": ("style.css", "text/css"),
}
STUDY_ROUTE = re.compile(r"/commons/api/studies/([a-f0-9]{16})(?:/(run|import|reproduce|review|export|submission))?\Z")
MAX_BODY = 2_000_000


class CommonsServer(HTTPServer):
    def __init__(self, root, port=8787, directory="artifacts/commons", seed=False):
        self.commons = Commons(root, directory)
        self.sessions = {}
        try:
            if seed:
                self.commons.seed()
            super().__init__(("127.0.0.1", port), Handler)
        except Exception:
            self.commons.close()
            raise

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server_port}"

    @property
    def cookie_name(self):
        return f"orc_{self.server_port}"

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address

    def server_close(self):
        super().server_close()
        self.commons.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, status, value, content_type="application/json", headers=None):
        data = (json.dumps(value, allow_nan=False).encode()
                if content_type == "application/json" else value)
        self.send_response(status)
        for name, value in {
            "Content-Type": f"{content_type}; charset=utf-8", "Content-Length": str(len(data)),
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            **(headers or {}),
        }.items():
            self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def error(self, status, message):
        self.send(status, {"error": {"message": message}})

    def host_ok(self):
        return (self.headers.get_all("Host") == [f"127.0.0.1:{self.server.server_port}"]
                and self.headers.get("Sec-Fetch-Site") != "cross-site")

    def session(self, create=False):
        now = time.monotonic()
        self.server.sessions = {k: v for k, v in self.server.sessions.items() if v["expires"] > now}
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie[self.server.cookie_name].value if self.server.cookie_name in cookie else ""
        except (ValueError, KeyError):
            token = ""
        value = self.server.sessions.get(token)
        if value or not create:
            return value, None
        if len(self.server.sessions) >= 64:
            raise LabError("local session limit reached; wait for session expiry")
        token = secrets.token_urlsafe(32)
        value = {"actor": "researcher", "csrf_token": secrets.token_urlsafe(32), "expires": now + 3600}
        self.server.sessions[token] = value
        return value, f"{self.server.cookie_name}={token}; Path=/commons/; HttpOnly; SameSite=Strict; Max-Age=3600"

    def do_GET(self):
        if not self.host_ok():
            return self.error(403, "Use the literal loopback address shown at startup.")
        try:
            if self.path in {"/", "/commons"}:
                return self.send(303, {}, headers={"Location": "/commons/"})
            if self.path in ASSETS:
                name, mime = ASSETS[self.path]
                return self.send(200, (Path(__file__).parent / "static" / name).read_bytes(), mime)
            if self.path == "/commons/api/session":
                session, cookie = self.session(create=True)
                return self.send(200, {"actor": session["actor"], "csrf_token": session["csrf_token"],
                                       "mode": "local_synthetic"},
                                 headers={"Set-Cookie": cookie} if cookie else None)
            session, _ = self.session()
            if not session:
                return self.error(401, "Local session expired. Reload to continue.")
            if self.path == "/commons/api/meta":
                return self.send(200, self.server.commons.metadata())
            if self.path == "/commons/api/studies":
                return self.send(200, {"studies": self.server.commons.listing()})
            route = STUDY_ROUTE.fullmatch(self.path)
            if route:
                sid, action = route.groups()
                if action == "export":
                    return self.send(200, self.server.commons.export(sid), headers={
                        "Content-Disposition": f'attachment; filename="commons-{sid}.json"'})
                if action == "submission":
                    return self.send(200, self.server.commons.get(sid)["submission"], headers={
                        "Content-Disposition": f'attachment; filename="submission-{sid}.json"'})
                if action is None:
                    return self.send(200, self.server.commons.get(sid))
            return self.error(404, "Resource not found.")
        except LabError as exc:
            return self.error(400, str(exc))
        except OSError:
            return self.error(503, "Local storage is unavailable. Preserve the journal and restart.")

    def do_POST(self):
        if not self.host_ok() or self.headers.get_all("Origin") != [self.server.origin]:
            return self.error(403, "Request origin rejected.")
        session, _ = self.session()
        if not session:
            return self.error(401, "Local session expired. Reload to continue.")
        csrf = self.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(csrf.encode(), session["csrf_token"].encode()):
            return self.error(403, "Request token rejected. Reload to continue.")
        try:
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
                return self.error(400, "One Content-Length is required; transfer encoding is unsupported.")
            length = int(lengths[0])
            if not 2 <= length <= MAX_BODY:
                return self.error(413, "Request exceeds the local size limit.")
            if self.headers.get_content_type() != "application/json":
                return self.error(415, "Use application/json.")
            body = json.loads(self.rfile.read(length), object_pairs_hook=_unique_pairs)
            _check_tree(body)
            if not isinstance(body, dict):
                raise LabError("request must be a JSON object")
            if self.path == "/commons/api/persona":
                if set(body) != {"actor"} or not isinstance(body["actor"], str) or body["actor"] not in PERSONAS:
                    raise LabError("unknown local persona")
                session["actor"] = body["actor"]
                return self.send(200, {"actor": session["actor"]})
            route = STUDY_ROUTE.fullmatch(self.path)
            if self.path == "/commons/api/studies":
                sid, action = None, "create"
            elif route and route.group(2) in {"run", "import", "reproduce", "review"}:
                sid, action = route.groups()
            else:
                return self.error(404, "Operation not found.")
            study = self.server.commons.mutate(session["actor"], action, sid, body,
                                               self.headers.get("Idempotency-Key", ""))
            return self.send(200, study)
        except (LabError, ValueError, UnicodeError, RecursionError, TypeError) as exc:
            return self.error(400, str(exc) if isinstance(exc, LabError) else "Invalid request data.")
        except OSError:
            return self.error(503, "Local storage is unavailable. Preserve the journal and restart.")
