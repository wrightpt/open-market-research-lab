"""Offline HTTPS fixture and actual stdio subprocess receipts. No remote calls."""

import json
import os
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from omr_mcp.bounds import MAX_LINE, MAX_REQUEST, MAX_RESPONSE, decode, encode
from omr_mcp.client import Config, ResearchClient, TOOLS, TransportError
from omr_mcp.protocol import LEGACY, MODERN, PREFIX, Protocol

ROOT = Path(__file__).resolve().parents[1]
TEST_KEY = "TEST_ONLY_NOT_A_REAL_KEY_0123456789"


def request(method="tools/list", identifier=1, **params):
    return {"jsonrpc": "2.0", "id": identifier, "method": method,
            "params": {"_meta": {PREFIX + "protocolVersion": MODERN, PREFIX + "clientCapabilities": {}}, **params}}


class Stub:
    def __init__(self):
        self.calls = []

    def call(self, name, arguments, cancel_event=None):
        self.calls.append((name, arguments))
        return {"synthetic": True, "rows": []}


class ConfigBoundsTests(unittest.TestCase):
    def test_https_origin_only(self):
        for origin in ("http://127.0.0.1", "http://localhost", "https://user:pass@localhost",
                       "https://localhost/data", "https://localhost?", "https://localhost#x",
                       "https://localhost:0", "https://localhost:65536", "https://localhost\n",
                       "https://localhost\\evil", "https://[::1%eth0]", "", "https://bad_name"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                Config.from_env({"OMR_API_URL": origin, "OMR_API_KEY": TEST_KEY})
        for origin in ("https://127.0.0.1:443", "https://[::1]:8443", "https://api.example.org/"):
            self.assertIsInstance(Config.from_env({"OMR_API_URL": origin, "OMR_API_KEY": TEST_KEY}), Config)

    def test_key_header_injection_and_repr(self):
        for key in ("", "short", TEST_KEY + "\r\nInjected: yes", TEST_KEY + "é", TEST_KEY + " ", "x" * 2049):
            with self.assertRaises(ValueError):
                Config.from_env({"OMR_API_URL": "https://localhost", "OMR_API_KEY": key})
        config = Config.from_env({"OMR_API_URL": "https://localhost", "OMR_API_KEY": TEST_KEY})
        self.assertNotIn(TEST_KEY, repr(config))

    def test_strict_json_duplicate_nonfinite_encoding_and_depth(self):
        for payload in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'\xff', b'{}{}', b'"\\ud800"', b'[' * 18 + b'0' + b']' * 18):
            with self.assertRaises((ValueError, UnicodeError)):
                decode(payload, MAX_LINE)
        with self.assertRaises(ValueError):
            encode({"x": "x" * MAX_REQUEST}, MAX_REQUEST)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.stub = Stub()
        self.protocol = Protocol(self.stub)

    def test_stateless_discovery_and_list_required_result_fields(self):
        result = self.protocol.prepare(request("server/discover"))["result"]
        self.assertEqual(result["supportedVersions"], [MODERN, LEGACY])
        self.assertEqual(result["resultType"], "complete")
        self.assertEqual(result["ttlMs"], 0)
        self.assertEqual(result["cacheScope"], "private")
        self.assertIn(PREFIX + "serverInfo", result["_meta"])
        listing = self.protocol.prepare(request())["result"]
        self.assertEqual([t["name"] for t in listing["tools"]], list(TOOLS))
        self.assertEqual(listing["ttlMs"], 0)
        self.assertEqual(self.stub.calls, [])

    def test_metadata_required_on_every_modern_request(self):
        self.protocol.prepare(request("server/discover"))
        for params in ({}, {"_meta": {}}, {"_meta": {PREFIX + "protocolVersion": MODERN}}, {"_meta": []}):
            reply = self.protocol.prepare({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": params})
            self.assertEqual(reply["error"]["code"], -32602)

    def test_public_tool_schemas_describe_shapes_without_entitlement_enums(self):
        listing = self.protocol.prepare(request())["result"]["tools"]
        schemas = {tool["name"]: tool["inputSchema"] for tool in listing}
        for name in ("list_datasets", "get_research_examples", "get_usage_limits"):
            self.assertEqual(schemas[name]["properties"], {})
        for name in ("describe_dataset", "get_coverage", "get_schema"):
            self.assertEqual(schemas[name]["required"], ["dataset"])
        query = schemas["query_timeseries"]
        self.assertEqual(query["properties"]["max_rows"]["maximum"], 500)
        self.assertEqual(set(query["required"]), {"dataset", "asset", "start", "end", "max_rows"})
        self.assertNotIn("enum", query["properties"]["dataset"])
        self.assertNotIn("enum", query["properties"]["asset"])
        # Schema discovery informs clients; only the backend decides entitlements.
        self.protocol.prepare(request("tools/call", name="query_timeseries", arguments={"dataset": "backend-decides"}))()
        self.assertEqual(self.stub.calls[0][1], {"dataset": "backend-decides"})

    def test_unsupported_version_has_modern_error(self):
        value = request()
        value["params"]["_meta"][PREFIX + "protocolVersion"] = "1900-01-01"
        reply = self.protocol.prepare(value)["error"]
        self.assertEqual(reply["code"], -32022)
        self.assertEqual(reply["data"], {"supported": [MODERN, LEGACY], "requested": "1900-01-01"})

    def test_legacy_initialize_requires_ready_notification_and_coexists(self):
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": LEGACY, "clientInfo": {"name": "fixture", "version": "1"}, "capabilities": {}}}
        reply = self.protocol.prepare(init)
        self.assertEqual(reply["result"]["protocolVersion"], LEGACY)
        self.assertNotIn("resultType", reply["result"])
        legacy_list = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        self.assertIn("error", self.protocol.prepare(legacy_list))
        self.assertIsNone(self.protocol.prepare({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(len(self.protocol.prepare(legacy_list)["result"]["tools"]), 7)
        self.assertEqual(self.protocol.prepare(request("ping", 3))["result"]["resultType"], "complete")
        self.assertIn("error", self.protocol.prepare(init))

    def test_other_legacy_version_not_falsely_advertised(self):
        value = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}
        self.assertEqual(self.protocol.prepare(value)["error"]["code"], -32602)

    def test_malformed_requests_and_batches(self):
        for value in ([], None, {}, {"jsonrpc": "2.0", "id": True, "method": "ping"},
                      {"jsonrpc": "2.0", "id": None, "method": "ping"}, {"jsonrpc": "2.0", "id": 1, "result": {}}):
            reply = self.protocol.prepare(value)
            self.assertEqual(reply["error"]["code"], -32600)
            if isinstance(value, dict) and type(value.get("id")) is int:
                self.assertEqual(reply["id"], value["id"])
            else:
                self.assertNotIn("id", reply)

    def test_unknown_methods_tools_and_nonobject_arguments(self):
        self.assertEqual(self.protocol.prepare(request("exec"))["error"]["code"], -32601)
        for name, args in (("https://evil.example", {}), ("../../keys", {}), ("trade", {}), ([], {}), ("list_datasets", [])):
            reply = self.protocol.prepare(request("tools/call", name=name, arguments=args))
            self.assertEqual(reply["error"]["code"], -32602)
        self.assertEqual(self.stub.calls, [])

    def test_tool_passthrough_does_not_forward_mcp_metadata(self):
        reply = self.protocol.prepare(request("tools/call", name="list_datasets", arguments={}))()
        self.assertFalse(reply["result"]["isError"])
        self.assertEqual(reply["result"]["structuredContent"]["rows"], [])
        self.assertEqual(self.stub.calls, [("list_datasets", {})])

    def test_notifications_never_execute_tools_or_respond(self):
        value = request("tools/call", name="list_datasets", arguments={})
        del value["id"]
        self.assertIsNone(self.protocol.prepare(value))
        self.assertEqual(self.stub.calls, [])

    def test_argument_body_bound(self):
        reply = self.protocol.prepare(request("tools/call", name="query_timeseries", arguments={"x": "x" * MAX_REQUEST}))
        self.assertEqual(reply["error"]["code"], -32602)
        self.assertEqual(self.stub.calls, [])


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.calls.append((self.path, dict(self.headers), body))
        mode = self.server.mode
        if mode == "delay":
            time.sleep(0.4)
        if mode == "redirect":
            self.send_response(307)
            self.send_header("Location", self.server.origin + "/should-never-follow")
            self.end_headers()
            return
        if mode == "denied":
            self.send_response(403)
            self.send_header("X-Private", TEST_KEY)
            self.end_headers()
            self.wfile.write(TEST_KEY.encode())
            return
        data = {"synthetic": True, "rows": [], "echo": json.loads(body)}
        if mode == "reflect":
            data["nested"] = [self.headers["X-API-Key"]]
        if mode == "deep":
            data = 0
            for _ in range(16):
                data = {"child": data}
        raw = json.dumps(data).encode()
        if mode == "malformed":
            raw = b'{"x": NaN}'
        if mode in {"oversize", "stream-oversize"}:
            raw = b"x" * (MAX_RESPONSE + 1)
        self.send_response(200)
        self.send_header("Content-Type", "text/html" if mode == "html" else "application/json")
        if mode == "compressed":
            self.send_header("Content-Encoding", "gzip")
        if mode != "stream-oversize":
            self.send_header("Content-Length", str(len(raw) + (5 if mode == "truncated" else 0)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass


class HttpsStdioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / "artifacts").mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="mcp-test-", dir=ROOT / "artifacts")
        cls.cert = Path(cls.temp.name) / "cert.pem"
        private = Path(cls.temp.name) / "test-key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-keyout", str(private), "-out", str(cls.cert), "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=IP:127.0.0.1,DNS:localhost"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cls.cert, private)
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        cls.server.origin = f"https://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def setUp(self):
        self.server.mode, self.server.calls = "ok", []
        self.env = {"OMR_API_URL": self.server.origin, "OMR_API_KEY": TEST_KEY, "OMR_CA_FILE": str(self.cert)}
        self.client = ResearchClient(Config.from_env(self.env))

    def run_stdio(self, lines, env=None):
        payload = b"".join(line if isinstance(line, bytes) else encode(line, MAX_LINE) + b"\n" for line in lines)
        completed = subprocess.run([os.sys.executable, "-m", "omr_mcp"], input=payload,
                                   capture_output=True, cwd=ROOT, env={**os.environ, **(env or self.env)}, timeout=15)
        self.assertNotIn(TEST_KEY.encode(), completed.stdout + completed.stderr)
        self.assertNotIn(str(ROOT).encode(), completed.stdout + completed.stderr)
        replies = [json.loads(line) for line in completed.stdout.splitlines()]
        return completed, replies

    def test_verified_https_fixed_method_path_key_header_and_object_body(self):
        self.assertTrue(self.client.call("list_datasets", {})["synthetic"])
        path, headers, body = self.server.calls[0]
        self.assertEqual(path, "/v1/research/tools/list_datasets")
        self.assertEqual(headers["X-API-Key"], TEST_KEY)
        self.assertEqual(headers["X-QMA-Client-Transport"], "mcp-public-adapter")
        self.assertNotIn("Authorization", headers)
        self.assertEqual(body, b"{}")

    def test_default_trust_rejects_self_signed_certificate(self):
        client = ResearchClient(Config.from_env({**self.env, "OMR_CA_FILE": ""}))
        with self.assertRaises(TransportError):
            client.call("list_datasets", {})
        self.assertEqual(self.server.calls, [])

    def test_hostname_verification_remains_enabled(self):
        self.assertTrue(self.client.context.check_hostname)
        self.assertEqual(self.client.context.verify_mode, ssl.CERT_REQUIRED)
        with self.assertRaises(ssl.SSLCertVerificationError):
            import socket
            with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=2) as raw:
                with self.client.context.wrap_socket(raw, server_hostname="wrong.example"):
                    pass

    def test_ambient_proxies_are_ignored(self):
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://127.0.0.1:1", "ALL_PROXY": "http://127.0.0.1:1", "https_proxy": "http://127.0.0.1:1", "NO_PROXY": ""}):
            self.assertTrue(self.client.call("get_schema", {})["synthetic"])

    def test_redirect_is_never_followed(self):
        self.server.mode = "redirect"
        with self.assertRaises(TransportError):
            self.client.call("list_datasets", {})
        self.assertEqual(len(self.server.calls), 1)

    def test_error_headers_and_bodies_do_not_leak(self):
        self.server.mode = "denied"
        completed, replies = self.run_stdio([request("tools/call", name="list_datasets", arguments={})])
        self.assertEqual(completed.returncode, 0)
        self.assertTrue(replies[0]["result"]["isError"])
        self.assertNotIn("X-Private", str(replies))
        self.assertEqual(completed.stderr, b"")

    def test_reflected_key_is_rejected_even_when_json_escaped(self):
        self.server.mode = "reflect"
        for key in (TEST_KEY, TEST_KEY + '"\\'):
            client = ResearchClient(Config.from_env({**self.env, "OMR_API_KEY": key}))
            with self.assertRaises(TransportError):
                client.call("list_datasets", {})

    def test_response_bounds_invalid_json_encoding_and_truncation(self):
        for mode in ("oversize", "stream-oversize", "malformed", "html", "compressed", "truncated"):
            with self.subTest(mode=mode):
                self.server.mode = mode
                with self.assertRaises(TransportError):
                    self.client.call("get_coverage", {})

    def test_argument_bound_before_any_https_request(self):
        with self.assertRaises(TransportError):
            self.client.call("query_timeseries", {"x": "x" * MAX_REQUEST})
        self.assertEqual(self.server.calls, [])

    def test_wall_deadline_including_resolver_and_worker_count(self):
        client = ResearchClient(Config.from_env(self.env), timeout=0.05)
        with patch.object(client, "_exchange", side_effect=lambda *_: time.sleep(0.3)):
            start = time.monotonic()
            with self.assertRaises(TransportError):
                client.call("list_datasets", {})
            self.assertLess(time.monotonic() - start, 0.25)
            with self.assertRaisesRegex(TransportError, "still active"):
                client.call("list_datasets", {})

    def test_cancelled_call_never_starts_https(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(TransportError):
            self.client.call("list_datasets", {}, cancel_event=cancelled)
        self.assertEqual(self.server.calls, [])

    def test_late_connection_never_sends_key_or_request(self):
        client = ResearchClient(Config.from_env(self.env), timeout=0.05)
        finished = threading.Event()
        with patch("omr_mcp.client.http.client.HTTPSConnection") as factory:
            connection = factory.return_value
            connection.connect.side_effect = lambda: time.sleep(0.15)
            connection.close.side_effect = finished.set
            with self.assertRaises(TransportError):
                client.call("list_datasets", {})
            self.assertTrue(finished.wait(1))
            connection.request.assert_not_called()

    def test_actual_stdio_modern_discovery_tool_and_legacy_initialize(self):
        legacy_init = {"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": {
            "protocolVersion": LEGACY, "capabilities": {}, "clientInfo": {"name": "fixture", "version": "1"}}}
        completed, replies = self.run_stdio([request("server/discover", 1),
            request("tools/call", 2, name="list_datasets", arguments={}), legacy_init,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/list"}])
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stderr, b"")
        by_id = {r["id"]: r["result"] for r in replies}
        self.assertEqual(set(by_id), {1, 2, 3, 4})
        self.assertEqual(by_id[1]["resultType"], "complete")
        self.assertTrue(by_id[2]["structuredContent"]["synthetic"])
        self.assertNotIn("resultType", by_id[4])

    def test_actual_stdio_legacy_tool_call(self):
        completed, replies = self.run_stdio([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": LEGACY, "capabilities": {}, "clientInfo": {"name": "fixture", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_usage_limits", "arguments": {}}}])
        self.assertEqual(completed.returncode, 0)
        self.assertTrue(replies[-1]["result"]["structuredContent"]["synthetic"])
        self.assertNotIn("resultType", replies[-1]["result"])

    def test_actual_stdio_maximum_backend_nesting_fits_result_envelope(self):
        self.server.mode = "deep"
        completed, replies = self.run_stdio([request("tools/call", name="get_schema")])
        self.assertEqual(completed.returncode, 0)
        self.assertFalse(replies[0]["result"]["isError"])

    def test_actual_stdio_parse_unknown_and_missing_metadata(self):
        completed, replies = self.run_stdio([b'{bad}\n', request("tools/call", name="not_allowed"),
                                           {"jsonrpc": "2.0", "id": 2, "method": "ping"}, b'[]\n'])
        self.assertEqual(completed.returncode, 0)
        self.assertEqual([r["error"]["code"] for r in replies], [-32700, -32602, -32602, -32600])
        self.assertNotIn("id", replies[0])
        self.assertNotIn("id", replies[-1])
        self.assertEqual(self.server.calls, [])

    def test_unknown_error_ids_are_omitted_in_both_supported_eras(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                preamble = [request("server/discover", "start")]
                known = request("not-a-method", "known")
                if legacy:
                    preamble = [{"jsonrpc": "2.0", "id": "start", "method": "initialize", "params": {
                        "protocolVersion": LEGACY, "capabilities": {}, "clientInfo": {"name": "fixture", "version": "1"}}},
                        {"jsonrpc": "2.0", "method": "notifications/initialized"}]
                    known = {"jsonrpc": "2.0", "id": "known", "method": "not-a-method"}
                completed, replies = self.run_stdio(preamble + [b'{broken}\n', b'[]\n', request("ping", None), known])
                self.assertEqual(completed.returncode, 0)
                for reply in replies[1:4]:
                    self.assertIn("error", reply)
                    self.assertNotIn("id", reply)
                self.assertEqual(replies[-1]["id"], "known")
                self.assertEqual(replies[-1]["error"]["code"], -32601)

    def test_actual_stdio_oversized_or_unterminated_line_exits(self):
        for line in (b"x" * (MAX_LINE + 1) + b"\n", b"{}"):
            completed, replies = self.run_stdio([line])
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(replies[0]["error"]["code"], -32600)

    def test_actual_stdio_cancellation_suppresses_late_response(self):
        self.server.mode = "delay"
        completed, replies = self.run_stdio([request("tools/call", 9, name="list_datasets"),
            {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 9}}, request("ping", 10)])
        self.assertEqual(completed.returncode, 0)
        self.assertEqual([r["id"] for r in replies], [10])

    def test_actual_stdio_concurrency_bound(self):
        self.server.mode = "delay"
        completed, replies = self.run_stdio([request("tools/call", 1, name="list_datasets"), request("tools/call", 2, name="get_schema")])
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(len(self.server.calls), 1)
        self.assertEqual({r["id"]: r for r in replies}[2]["error"]["code"], -32000)

    def test_config_error_is_only_generic_stderr(self):
        completed, replies = self.run_stdio([], {**self.env, "OMR_API_URL": "http://localhost"})
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(replies, [])
        self.assertIn(b"Invalid adapter configuration", completed.stderr)
