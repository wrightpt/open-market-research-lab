"""Literal-loopback-only x402-v2-shaped HTTP sandbox. NOT a payment server.

Only fake, ephemeral fixture tokens and HMAC stub proofs are accepted. This
entry point has NO connection to the existing public/production services.
"""
import json
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from market_lab.io import ROOT, LabError, _check_tree, _unique_pairs
from .ledger import FixtureRegistry, OfflineLedger, MeterError
from .sandbox_identity import DevTokenIssuer, IdentityError, encode_header, decode_header
from .sandbox_payments import SandboxExchange, SandboxReject

MAX_BODY_BYTES = 4096
RECEIPT = re.compile(r"/sandbox/receipt/([a-f0-9]{32})\Z")


class SandboxHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8
    allow_reuse_address = False

    def __init__(self, root=ROOT, *, port=0, directory="artifacts/x402-sandbox",
                 registry=None, clock=None):
        self.registry = registry or FixtureRegistry()
        self.ledger = OfflineLedger(root, self.registry, directory=directory, clock=clock)
        self.issuer = DevTokenIssuer(now=self.ledger.clock)
        try:
            self.exchange = SandboxExchange(self.ledger, self.issuer)
            super().__init__(("127.0.0.1", port), SandboxHandler)
        except BaseException:
            self.ledger.close()
            raise

    @property
    def origin(self):
        return "http://127.0.0.1:" + str(self.server_port)

    @property
    def resource_url(self):
        return self.origin + "/sandbox/resource"

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address

    def server_close(self):
        try:
            super().server_close()
        finally:
            self.ledger.close()


class SandboxHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        # Do not log tokens, proof headers or request bodies.
        pass

    def send(self, status, body, *, headers=None):
        raw = json.dumps(body, allow_nan=False, separators=(",", ":")).encode()
        self.send_response(status)
        fixed = {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(raw)),
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
        }
        fixed.update(headers or {})
        for key, value in fixed.items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def error(self, status, code):
        self.send(status, {"error": code, "mode": "zero_funds_sandbox_only"})

    def origin_ok(self):
        if self.headers.get_all("Host", []) != [f"127.0.0.1:{self.server.server_port}"]:
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return False
        origins = self.headers.get_all("Origin", [])
        return not origins or origins == [self.server.origin]

    def principal(self):
        auth = self.headers.get_all("Authorization", [])
        if len(auth) != 1 or not auth[0].startswith("Bearer ") or len(auth[0]) > 2048:
            raise IdentityError("development bearer token required")
        return self.server.issuer.verify(auth[0][7:], self.server.registry)

    def body(self):
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or self.headers.get("Transfer-Encoding") is not None:
            raise SandboxReject("single_content_length_required", 400)
        if self.headers.get_content_type() != "application/json":
            raise SandboxReject("json_content_type_required", 415)
        try:
            size = int(lengths[0])
        except ValueError as exc:
            raise SandboxReject("invalid_content_length", 400) from exc
        if not 2 <= size <= MAX_BODY_BYTES:
            raise SandboxReject("body_size_out_of_bounds", 413)
        try:
            value = json.loads(self.rfile.read(size), object_pairs_hook=_unique_pairs)
            _check_tree(value)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise SandboxReject("invalid_json_body", 400) from exc
        if type(value) is not dict or set(value) != {"sku", "params", "key"}:
            raise SandboxReject("invalid_request_shape", 400)
        return value

    def do_GET(self):
        if not self.origin_ok():
            return self.error(403, "literal_loopback_origin_required")
        match = RECEIPT.fullmatch(self.path)
        if not match:
            return self.error(404, "route_not_found")
        try:
            principal = self.principal()
            receipt = self.server.ledger.get(principal, match.group(1))
            self.send(200, receipt)
        except IdentityError:
            self.error(401, "invalid_development_identity")
        except MeterError:
            self.error(404, "receipt_not_found")
        except (OSError, LabError):
            self.error(503, "sandbox_storage_unavailable")

    def do_POST(self):
        if not self.origin_ok():
            return self.error(403, "literal_loopback_origin_required")
        if self.path != "/sandbox/resource":
            return self.error(404, "route_not_found")
        try:
            principal = self.principal()
            args = self.body()
            signature = self.headers.get_all("PAYMENT-SIGNATURE", [])
            if len(signature) > 1:
                raise SandboxReject("duplicate_payment_signature")
            if signature:
                decoded = decode_header(signature[0])
                receipt = self.server.exchange.fulfill(
                    principal, args["key"], args["sku"], args["params"],
                    decoded, self.server.resource_url)
                if receipt["state"] == "settled":
                    payment_response = self.server.exchange.payment_response(
                        principal, receipt["id"])
                    return self.send(200, {"receipt": receipt},
                                     headers={"PAYMENT-RESPONSE": encode_header(payment_response)})
                return self.send(409, {"receipt": receipt})
            challenged = self.server.exchange.challenge(
                principal, args["key"], args["sku"], args["params"],
                self.server.resource_url)
            if challenged["status"] == 402:
                return self.send(402, {
                    "error": "payment_required",
                    "mode": "zero_funds_sandbox_only",
                    "receipt_id": challenged["receipt_id"],
                }, headers={"PAYMENT-REQUIRED": encode_header(challenged["required"])})
            if challenged["status"] == 200:
                response = self.server.exchange.payment_response(
                    principal, challenged["receipt"]["id"])
                return self.send(200, {"receipt": challenged["receipt"]},
                                 headers={"PAYMENT-RESPONSE": encode_header(response)})
            return self.send(409, {"receipt": challenged["receipt"]})
        except IdentityError:
            self.error(401, "invalid_development_identity")
        except SandboxReject as exc:
            self.error(exc.status, exc.code)
        except MeterError:
            self.error(409, "sandbox_budget_or_request_rejected")
        except (OSError, LabError):
            self.error(503, "sandbox_research_unavailable")
        except Exception:
            self.error(503, "sandbox_internal_error")
