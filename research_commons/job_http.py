"""Authenticated loopback test API. Never mount this fixture on a public service."""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from market_lab.io import ROOT, LabError, _check_tree, _unique_pairs
from .ledger import MeterError
from .job_queue import JobService
from .job_contract import catalog
from .sandbox_identity import DevTokenIssuer, IdentityError

JOB = re.compile(r"/v1/jobs/([a-f0-9]{32})(?:/(history|result|manifest|cancel))?\Z")


class JobHTTPServer(ThreadingHTTPServer):
    daemon_threads = False
    request_queue_size = 8
    allow_reuse_address = False

    def __init__(self, root=ROOT, *, port=0, directory="artifacts/research-jobs",
                 registry=None, clock=None, entitlements=None, start_worker=True):
        self.jobs = JobService(root, directory=directory, registry=registry,
                               clock=clock, entitlements=entitlements)
        self.registry = self.jobs.registry
        # Reuse the existing explicitly fake fixture issuer. There is no network
        # token-minting route; restart invalidates all old bearer credentials.
        self.issuer = DevTokenIssuer(now=self.jobs.ledger.clock)
        self._slots = threading.BoundedSemaphore(8)
        try:
            super().__init__(("127.0.0.1", port), JobHandler)
            if start_worker:
                self.jobs.start()
        except BaseException:
            self.jobs.close()
            raise

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server_port}"

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(5)
        return request, address

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def server_close(self):
        super().server_close()
        self.jobs.close()


class JobHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass  # No credentials, bodies or query strings in logs.

    def send(self, status, value):
        raw = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
        self.close_connection = True
        self.send_response(status)
        for key, val in {
            "Content-Type": "application/json", "Content-Length": str(len(raw)),
            "Connection": "close", "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
        }.items():
            self.send_header(key, val)
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def principal(self):
        if (self.headers.get_all("Host", []) != [f"127.0.0.1:{self.server.server_port}"]
                or self.headers.get_all("Origin", []) not in ([], [self.server.origin])
                or self.headers.get("Sec-Fetch-Site") == "cross-site"):
            raise IdentityError("invalid origin")
        auth = self.headers.get_all("Authorization", [])
        if len(auth) != 1 or not auth[0].startswith("Bearer ") or len(auth[0]) > 2048:
            raise IdentityError("fixture credential required")
        return self.server.issuer.verify(auth[0][7:], self.server.registry)

    def body(self):
        length = self.headers.get_all("Content-Length", [])
        if (len(length) != 1 or not length[0].isascii() or not length[0].isdigit()
                or self.headers.get("Transfer-Encoding") is not None
                or self.headers.get_content_type() != "application/json"):
            raise LabError("invalid request framing")
        size = int(length[0])
        if not 2 <= size <= 40000:
            raise LabError("request too large")
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise LabError("incomplete request")
        value = json.loads(raw, object_pairs_hook=_unique_pairs)
        _check_tree(value)
        if type(value) is not dict:
            raise LabError("object required")
        return value

    def do_GET(self):
        try:
            principal = self.principal()
            jobs = self.server.jobs
            if self.path == "/v1/catalog":
                jobs._allow(principal)
                return self.send(200, catalog(jobs.root))
            if self.path == "/v1/jobs":
                return self.send(200, {"jobs": jobs.listing(principal)})
            if self.path == "/v1/credits":
                return self.send(200, jobs.ledger.balance(principal))
            match = JOB.fullmatch(self.path)
            if not match or match[2] == "cancel":
                return self.send(404, {"error": "not_found"})
            operation = {None: jobs.get, "history": jobs.history, "result": jobs.result,
                         "manifest": jobs.result_manifest}[match[2]]
            return self.send(200, operation(principal, match[1]))
        except IdentityError:
            self.send(401, {"error": "invalid_fixture_identity"})
        except MeterError:
            self.send(404, {"error": "not_found_or_unavailable"})
        except (LabError, OSError, ValueError):
            self.send(503, {"error": "evidence_or_storage_unavailable"})

    def do_POST(self):
        try:
            principal = self.principal()
            body = self.body()
            jobs = self.server.jobs
            if self.path == "/v1/events/read" and set(body) <= {"consumer", "after", "limit"} and "consumer" in body:
                return self.send(200, jobs.events.read(principal, body["consumer"],
                                 after=body.get("after"), limit=body.get("limit", 16)))
            if self.path == "/v1/events/ack" and set(body) == {"consumer", "event_id"}:
                return self.send(200, jobs.events.acknowledge(principal, body["consumer"], body["event_id"]))
            if self.path == "/v1/quote" and set(body) == {"spec"}:
                return self.send(200, jobs.quote(principal, body["spec"]))
            if self.path == "/v1/jobs" and set(body) == {"key", "spec"}:
                return self.send(202, jobs.submit(principal, body["key"], body["spec"]))
            match = JOB.fullmatch(self.path)
            if match and match[2] == "cancel" and body == {}:
                return self.send(200, jobs.cancel(principal, match[1]))
            self.send(400, {"error": "unsupported_request"})
        except IdentityError:
            self.send(401, {"error": "invalid_fixture_identity"})
        except MeterError:
            self.send(409, {"error": "admission_or_state_rejected"})
        except (LabError, ValueError, TypeError, RecursionError):
            self.send(400, {"error": "invalid_request"})
        except OSError:
            self.send(503, {"error": "storage_unavailable"})
