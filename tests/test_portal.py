import http.client
import json
import threading
import unittest
from pathlib import Path

from developer_portal.demo import DemoServer
from developer_portal.catalog import datasets
from market_lab.fixtures import expected_manifest


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.server = DemoServer()
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(3)

    def request(self, path, method="GET", body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=4)
        conn.request(method, path, body=json.dumps(body) if body is not None else None,
                     headers=headers or {})
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def mutation(self, path, body=None, method="POST"):
        return self.request(path, method, body, {"Origin": self.server.origin,
                                                "X-CSRF-Token": self.server.csrf})

    def test_loopback_only_allowlisted_assets_and_no_store(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        for path in ("/portal/", "/portal/app.js", "/portal/style.css", "/portal/state.mjs"):
            status, headers, _ = self.request(path)
            self.assertEqual(status, 200)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        for path in ("/portal/../AGENTS.md", "/.git/config", "/portal/static/../../README.md"):
            self.assertEqual(self.request(path)[0], 404)

    def test_host_origin_csrf_rejections(self):
        self.assertEqual(self.request("/portal/", headers={"Host": "untrusted.invalid"})[0], 403)
        self.assertEqual(self.request("/portal/api/logout", "POST", {})[0], 403)
        self.assertEqual(self.request("/portal/api/logout", "POST", {}, {"Origin": self.server.origin})[0], 403)

    def test_login_is_explicit_mock_notice(self):
        status, _, body = self.request("/portal/auth/github")
        self.assertEqual(status, 200)
        self.assertIn(b"No GitHub login", body)

    def test_pending_denied_and_unapproved_never_create_keys(self):
        for scenario in ("anonymous", "pending", "denied", "unrequested"):
            self.mutation("/portal/demo/scenario", {"scenario": scenario})
            self.assertEqual(self.mutation("/portal/api/keys", {"name": "test"})[0], 403)

    def test_access_request_becomes_pending_without_approval(self):
        self.mutation("/portal/demo/scenario", {"scenario": "unrequested"})
        self.assertEqual(self.mutation("/portal/api/access-requests", {"purpose": "Reproduce causal liquidity alert fixture tests."})[0], 202)
        self.assertEqual(json.loads(self.request("/portal/api/session")[2])["user"]["access_status"], "pending")

    def test_key_once_only_rotate_revoke_and_logout(self):
        self.mutation("/portal/demo/scenario", {"scenario": "approved"})
        created = json.loads(self.mutation("/portal/api/keys", {"name": "local-test", "scopes": ["research:read"], "expires_in_days": 30})[2])
        self.assertTrue(created["secret"].startswith("DEMO_NOT_A_CREDENTIAL_"))
        self.assertNotIn(created["secret"].encode(), self.request("/portal/api/keys")[2])
        rotated = json.loads(self.mutation(f'/portal/api/keys/{created["key"]["id"]}/rotate', {})[2])
        self.assertNotEqual(rotated["secret"], created["secret"])
        self.assertTrue(json.loads(self.request("/portal/api/keys")[2])["keys"][0]["revoked"])
        self.assertEqual(self.mutation(f'/portal/api/keys/{rotated["key"]["id"]}', method="DELETE")[0], 200)
        self.mutation("/portal/api/logout", {})
        self.assertFalse(json.loads(self.request("/portal/api/session")[2])["authenticated"])

    def test_failure_and_invalid_input_states(self):
        self.assertEqual(self.mutation("/portal/demo/scenario", {"scenario": "unknown"})[0], 400)
        self.mutation("/portal/demo/scenario", {"scenario": "failure"})
        self.assertEqual(self.request("/portal/api/datasets")[0], 503)
        self.assertEqual(self.request("/portal/api/session")[0], 200)
        self.assertEqual(self.mutation("/portal/demo/scenario", {"scenario": "x" * 5000})[0], 413)

    def test_key_names_and_per_minute_quota_match_public_contract(self):
        self.mutation("/portal/demo/scenario", {"scenario": "approved"})
        body = {"scopes": ["research:read"], "expires_in_days": 30}
        for name in ("", " ", "x" * 65, "clé", "name\n"):
            self.assertEqual(self.mutation("/portal/api/keys", {**body, "name": name})[0], 400)
        for name in ("a", "x" * 64):
            self.assertEqual(self.mutation("/portal/api/keys", {**body, "name": name})[0], 201)
        self.assertIn("requests_per_minute", json.loads(self.request("/portal/api/usage")[2])["limits"])

    def test_catalog_matches_public_fixture_identity(self):
        dataset = datasets()[0]
        self.assertTrue(dataset["synthetic"])
        self.assertEqual(len(dataset["fields"]), 10)
        self.assertEqual(dataset["schema_version"], 1)
        self.assertIn("bar close", dataset["time_basis"])
        metadata = expected_manifest()
        for coverage in dataset["coverage"]:
            self.assertEqual(coverage["sha256"], metadata["splits"][coverage["split"]]["sha256"])

    def test_browser_code_uses_no_html_injection_or_persistent_credentials(self):
        root = Path(__file__).resolve().parents[1] / "developer_portal/static"
        code = (root / "app.js").read_text() + (root / "state.mjs").read_text()
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "localStorage", "sessionStorage", "document.cookie", "eval("):
            self.assertNotIn(forbidden, code)


if __name__ == "__main__":
    unittest.main()
