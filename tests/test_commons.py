"""Persistent evidence semantics and actual loopback HTTP boundary checks."""

import copy
import http.client
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from helpers import RepoTest, baseline
from market_lab.io import LabError, canonical_bytes, object_hash
from market_lab.research import CONSUMED
from research_commons.journal import Journal
from research_commons.server import CommonsServer
from research_commons.service import Commons


class CommonsTests(RepoTest):
    def setUp(self):
        super().setUp()
        self.app = Commons(self.root)
        self.addCleanup(lambda: self.app.close())

    def create(self, parent=None):
        submission = baseline()
        submission["submission_id"] = "study-" + uuid.uuid4().hex
        return self.app.mutate("researcher", "create", None,
                               {"submission": submission, "parent_id": parent}, uuid.uuid4().hex)

    def mutate(self, action, sid, body=None, actor="researcher", key=None):
        return self.app.mutate(actor, action, sid, body or {}, key or uuid.uuid4().hex)

    def test_complete_workflow_roundtrips_after_restart_without_holdout(self):
        study = self.create()
        from research_commons.service import load_split
        with patch("research_commons.service.load_split", wraps=load_split) as loader:
            self.mutate("run", study["id"])
            result = self.mutate("reproduce", study["id"], actor="reviewer")
        self.assertTrue(all(c.args[1] == "development" for c in loader.call_args_list))
        self.assertFalse((self.root / CONSUMED).exists())
        self.assertEqual(result["status"], "reproduced")
        self.assertEqual(result["evidence"]["sha256"], result["reproduction"]["sha256"])
        self.mutate("review", study["id"], {
            "verdict": "accepted", "rationale": "The complete report reproduced in this local workflow.",
            "conflicts": "Local demo personas only.",
        }, actor="reviewer")
        package = self.app.export(study["id"])
        self.assertEqual(package["study_sha256"], object_hash(package["study"]))
        self.app.close()
        self.app = Commons(self.root)
        self.assertEqual(package, self.app.export(study["id"]))

    def test_mismatched_import_is_preserved_and_cannot_be_accepted(self):
        study = self.create()
        report = self.app._report(study)
        report["summary"]["fees_paid"] += 1
        self.mutate("import", study["id"], {"report": report})
        result = self.mutate("reproduce", study["id"], actor="reviewer")
        self.assertEqual(result["status"], "disputed")
        self.assertEqual(result["reproduction"]["differing_sections"], ["summary"])
        self.assertEqual(result["evidence"]["report"], report)
        with self.assertRaisesRegex(LabError, "mismatched"):
            self.mutate("review", study["id"], {"verdict": "accepted", "rationale": "x" * 25,
                                               "conflicts": "None known"}, actor="reviewer")
        rejected = self.mutate("review", study["id"], {"verdict": "rejected", "rationale": "Fees differ from the reproduced accounting ledger.",
                                                       "conflicts": "Local demonstration."}, actor="reviewer")
        self.assertEqual(rejected["reviews"][0]["verdict"], "rejected")

    def test_reproduction_checks_entire_report_including_non_summary_fields(self):
        study = self.create()
        report = self.app._report(study)
        report["decisions"][0]["target"] = 1
        self.mutate("import", study["id"], {"report": report})
        result = self.mutate("reproduce", study["id"], actor="reviewer")
        self.assertEqual(result["reproduction"]["differing_sections"], ["decisions"])

    def test_idempotency_survives_restart_and_conflicting_input_is_rejected(self):
        study = self.create()
        self.mutate("run", study["id"], key="repeatable-key")
        count = len(self.app.journal.events)
        self.app.close()
        self.app = Commons(self.root)
        result = self.mutate("run", study["id"], key="repeatable-key")
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(len(self.app.journal.events), count)
        with self.assertRaisesRegex(LabError, "different input"):
            self.mutate("run", study["id"], {"unexpected": True}, key="repeatable-key")

    def test_concurrent_duplicate_requests_compute_once(self):
        sid = self.create()["id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.mutate("run", sid, key="concurrent-request"), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(self.app.get(sid)["attempts"]), 1)

    def test_persona_and_transition_rules_are_enforced_by_service(self):
        sid = self.create()["id"]
        with self.assertRaises(LabError):
            self.mutate("run", sid, actor="reviewer")
        self.mutate("run", sid)
        with self.assertRaises(LabError):
            self.mutate("reproduce", sid)
        with self.assertRaises(LabError):
            self.mutate("run", sid)
        with self.assertRaises(LabError):
            self.mutate("review", sid, {"verdict": "accepted", "rationale": "x" * 25, "conflicts": "None known"}, actor="reviewer")

    def test_failed_attempt_remains_and_explicit_retry_gets_a_new_receipt(self):
        sid = self.create()["id"]
        with patch("research_commons.service.build_report", side_effect=LabError("broken fixture")):
            result = self.mutate("run", sid, key="failed-attempt")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.mutate("run", sid, key="failed-attempt")["status"], "failed")
        retried = self.mutate("run", sid)
        self.assertEqual([a["status"] for a in retried["attempts"]], ["failed", "completed"])

    def test_process_interruption_is_retained_as_failed_not_automatically_retried(self):
        sid = self.create()["id"]
        fingerprint = object_hash({"action": "run", "study_id": sid, "body": {}})
        self.app._append("researcher", "run_started", sid, "interrupted-key", fingerprint, {})
        self.app.close()
        self.app = Commons(self.root)
        self.assertEqual(self.app.get(sid)["status"], "failed")
        self.assertEqual(self.mutate("run", sid, key="interrupted-key")["status"], "failed")

    def test_import_after_failed_run_preserves_the_failed_attempt(self):
        study = self.create()
        report = self.app._report(study)
        with patch("research_commons.service.build_report", side_effect=LabError("broken fixture")):
            self.mutate("run", study["id"])
        imported = self.mutate("import", study["id"], {"report": report})
        self.assertEqual(imported["status"], "submitted")
        self.assertEqual(imported["attempts"][0]["status"], "failed")
        self.assertIn("message", imported["attempts"][0])

    def test_fork_keeps_parent_evidence_unchanged(self):
        sid = self.create()["id"]
        self.mutate("run", sid)
        before = self.app.export(sid)
        fork = self.create(parent=sid)
        self.assertEqual(fork["parent_id"], sid)
        self.assertEqual(before, self.app.export(sid))

    def test_source_drift_fails_before_evidence_admission(self):
        sid = self.create()["id"]
        path = self.root / "market_lab/strategy.py"
        path.write_text(path.read_text() + "\n# changed source\n")
        result = self.mutate("run", sid)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["evidence"])

    def test_running_process_cannot_pin_changed_files_as_its_loaded_engine(self):
        path = self.root / "market_lab/strategy.py"
        path.write_text(path.read_text() + "\n# changed while server was running\n")
        with self.assertRaisesRegex(LabError, "restart"):
            self.create()
        self.assertEqual(self.app.listing(), [])

    def test_import_wrong_provenance_or_holdout_is_rejected(self):
        study = self.create()
        report = self.app._report(study)
        report["provenance"]["split"] = "holdout"
        with self.assertRaisesRegex(LabError, "exact submission"):
            self.mutate("import", study["id"], {"report": report})
        self.assertEqual(self.app.get(study["id"])["status"], "draft")

    def test_arbitrary_submission_code_fields_are_rejected(self):
        submission = baseline()
        submission["strategy"]["command"] = "do not execute"
        with self.assertRaises(LabError):
            self.app.mutate("researcher", "create", None,
                            {"submission": submission, "parent_id": None}, "bad-submission")
        self.assertEqual(self.app.listing(), [])

    def test_second_writer_and_symlink_state_are_rejected(self):
        with self.assertRaisesRegex(LabError, "active writer"):
            Journal(self.root)
        (self.root / "artifacts/link").symlink_to(self.root / "artifacts/commons", target_is_directory=True)
        with self.assertRaisesRegex(LabError, "symlink"):
            Journal(self.root, "artifacts/link")

    def test_corrupted_event_fails_closed_on_restart(self):
        sid = self.create()["id"]
        self.mutate("run", sid)
        self.app.close()
        first = self.root / "artifacts/commons/events/000001.json"
        data = json.loads(first.read_text())
        data["payload"]["submission"]["title"] = "changed"
        first.write_bytes(canonical_bytes(data))
        with self.assertRaisesRegex(LabError, "hash verification"):
            Commons(self.root)

    def test_seed_is_idempotent_and_marks_example_reviews_as_demonstrations(self):
        self.app.seed()
        before = copy.deepcopy(self.app.listing())
        self.app.seed()
        self.assertEqual(before, self.app.listing())
        self.assertEqual({s["status"] for s in before}, {"reproduced", "disputed"})
        self.assertTrue(all("demonstration" in s["reviews"][0]["conflicts"] for s in before))


class CommonsHTTPTests(RepoTest):
    def setUp(self):
        super().setUp()
        self.server = CommonsServer(self.root, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.cookie = None
        self.csrf = None
        status, data, headers = self.request("GET", "/commons/api/session")
        self.assertEqual(status, 200)
        self.cookie = headers["Set-Cookie"].split(";")[0]
        self.csrf = data["csrf_token"]

    def stop(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def request(self, method, path, body=None, override=None, raw=None):
        headers = {"Host": f"127.0.0.1:{self.server.server_port}"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if method == "POST":
            headers.update({"Content-Type": "application/json", "Origin": self.server.origin,
                            "X-CSRF-Token": self.csrf or "", "Idempotency-Key": uuid.uuid4().hex})
        headers.update(override or {})
        payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            data = response.read()
            if "application/json" in response.getheader("Content-Type", ""):
                data = json.loads(data)
            return response.status, data, dict(response.getheaders())
        finally:
            connection.close()

    def test_actual_http_create_run_replay_and_export(self):
        status, study, _ = self.request("POST", "/commons/api/studies", {"submission": baseline(), "parent_id": None})
        self.assertEqual(status, 200)
        route = f'/commons/api/studies/{study["id"]}'
        self.assertEqual(self.request("POST", route + "/run", {})[1]["status"], "submitted")
        self.assertEqual(self.request("POST", "/commons/api/persona", {"actor": "reviewer"})[0], 200)
        self.assertTrue(self.request("POST", route + "/reproduce", {})[1]["reproduction"]["matched"])
        status, package, headers = self.request("GET", route + "/export")
        self.assertEqual(status, 200)
        self.assertEqual(package["study_sha256"], object_hash(package["study"]))
        self.assertIn("attachment", headers["Content-Disposition"])

    def test_host_origin_csrf_and_session_boundaries(self):
        self.assertEqual(self.request("GET", "/commons/", override={"Host": "attacker.invalid"})[0], 403)
        self.assertEqual(self.request("POST", "/commons/api/persona", {}, {"Origin": "https://attacker.invalid"})[0], 403)
        self.assertEqual(self.request("POST", "/commons/api/persona", {}, {"X-CSRF-Token": "wrong"})[0], 403)
        self.assertEqual(self.request("GET", "/commons/api/studies", override={"Cookie": ""})[0], 401)
        self.assertEqual(self.request("GET", "/commons/api/session", override={"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_malformed_json_duplicate_fields_nonfinite_and_oversize_fail_closed(self):
        for payload in (b'{"actor":"researcher","actor":"reviewer"}', b'{"n":NaN}', b'[]', b'{bad json', b'{"n":' + b'[' * 50 + b'0' + b']' * 50 + b'}'):
            self.assertEqual(self.request("POST", "/commons/api/persona", raw=payload)[0], 400)
        self.assertEqual(self.request("POST", "/commons/api/persona", raw=b"{}", override={"Content-Length": "2000001"})[0], 413)
        self.assertEqual(self.request("POST", "/commons/api/persona", raw=b"{}", override={"Content-Type": "text/plain"})[0], 415)

    def test_asset_allowlist_and_browser_headers(self):
        for path in ("/commons/", "/commons/app.js", "/commons/style.css"):
            status, _, headers = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.request("GET", "/commons/../../AGENTS.md")[0], 404)

    def test_missing_idempotency_key_cannot_create_evidence(self):
        status, _, _ = self.request("POST", "/commons/api/studies", {"submission": baseline(), "parent_id": None}, {"Idempotency-Key": ""})
        self.assertEqual(status, 400)
        self.assertEqual(self.server.commons.listing(), [])
