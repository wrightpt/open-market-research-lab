"""Tenant event replay, real crash boundaries and non-dispatch admission tests."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from market_lab.io import ROOT, load_json, object_hash
from research_commons.job_contract import LIMITS, job_source_hash
from research_commons.job_handoff import GATES, TARGETS, preview_handoff
from research_commons.job_http import JobHTTPServer
from research_commons.job_queue import JobService
from research_commons.ledger import MeterError


def spec():
    return {"submission": load_json(ROOT / "submissions/baseline.json"),
            "split": "development", "resources": dict(LIMITS), "max_price_cents": 50}


class EventTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "artifacts").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="job-events-", dir=ROOT / "artifacts")
        self.directory = "artifacts/" + Path(self.temp.name).name
        self.jobs = JobService(ROOT, directory=self.directory)
        self.identities()

    def identities(self):
        self.a = self.jobs.registry.issue("demo-alpha")
        self.b = self.jobs.registry.issue("demo-beta")

    def tearDown(self):
        self.jobs.close()
        self.temp.cleanup()

    def restart(self):
        self.jobs.close()
        self.jobs = JobService(ROOT, directory=self.directory)
        self.identities()

    def submit(self, key="event-job-0001", principal=None):
        return self.jobs.submit(principal or self.a, key, spec())

    def read(self, **kw):
        return self.jobs.events.read(self.a, "research-ui", **kw)

    def ack(self, event):
        return self.jobs.events.acknowledge(self.a, "research-ui", event["event_id"])

    def test_read_and_disconnect_do_not_ack_execute_or_charge(self):
        job = self.submit()
        first = self.read()
        self.assertIsNone(first["acknowledgment"])
        self.assertEqual(first, self.read())
        self.restart()
        self.assertEqual(first, self.read())
        self.assertEqual(self.submit()["id"], job["id"])
        self.assertEqual(self.jobs.get(self.a, job["id"])["status"], "queued")
        self.assertEqual(self.jobs.ledger.balance(self.a)["spent_cents"], 0)

    def test_lost_ack_reply_retries_exact_receipt_after_restart(self):
        job = self.submit()
        event = self.read()["events"][0]
        ack = self.ack(event)
        self.restart()
        self.assertEqual(ack, self.ack(event))
        self.assertEqual(self.read()["events"], [])
        self.jobs.run_one()
        self.assertEqual([e["status"] for e in self.read()["events"]], ["running", "succeeded"])
        self.assertEqual(self.jobs.get(self.a, job["id"])["charged_cents"], 50)

    def test_concurrent_duplicate_ack_is_one_observation(self):
        self.submit()
        event = self.read()["events"][0]
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.ack(event), range(16)))
        self.assertEqual(len({r["receipt_sha256"] for r in results}), 1)
        with self.jobs.ledger.transaction() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM job_event_acks").fetchone()[0], 1)
        self.assertEqual(self.jobs.ledger.balance(self.a)["operations"], 1)

    def test_ack_gap_denied_and_explicit_old_page_replay_allowed(self):
        self.submit()
        self.jobs.run_one()
        events = self.read()["events"]
        with self.assertRaisesRegex(MeterError, "in order"):
            self.ack(events[-1])
        for event in events:
            self.ack(event)
        self.assertEqual(self.read()["events"], [])
        self.assertEqual(self.read(after="start")["events"], events)
        self.assertEqual(self.read(after=events[0]["event_id"])["events"], events[1:])

    def test_cross_tenant_event_cursor_ack_and_manifest_denied(self):
        job = self.submit()
        self.jobs.run_one()
        event = self.read()["events"][0]
        other = self.jobs.events.read(self.b, "research-ui")
        self.assertEqual(other["events"], [])
        for fn in (lambda: self.jobs.events.read(self.b, "research-ui", after=event["event_id"]),
                   lambda: self.jobs.events.acknowledge(self.b, "research-ui", event["event_id"]),
                   lambda: self.jobs.result_manifest(self.b, job["id"]),
                   lambda: preview_handoff(self.jobs, self.b, event["event_id"], "beads")):
            with self.assertRaises(MeterError):
                fn()
        self.assertNotIn("seq", event)
        self.assertNotIn("tenant", event)

    def test_fixed_consumers_have_independent_cursors(self):
        self.submit()
        event = self.read()["events"][0]
        self.ack(event)
        self.assertEqual(len(self.jobs.events.read(self.a, "runtime-simulation")["events"]), 1)
        with self.assertRaises(MeterError):
            self.jobs.events.read(self.a, "arbitrary-customer-name")

    def test_page_and_cursor_bounds_reject_bool_and_malformed(self):
        self.submit()
        for limit in (0, -1, 33, True, "2"):
            with self.subTest(limit=limit), self.assertRaises(MeterError):
                self.read(limit=limit)
        for after in (1, [], "no", "f" * 64):
            with self.subTest(after=after), self.assertRaises(MeterError):
                self.read(after=after)
        self.jobs.run_one()
        first = self.read(limit=1)
        self.assertTrue(first["has_more"])
        self.assertEqual(len(self.read(after=first["next_cursor"], limit=2)["events"]), 2)

    def test_storage_failure_leaves_no_ack_and_retry_still_possible(self):
        self.submit()
        event = self.read()["events"][0]
        with mock.patch.object(self.jobs.events, "_admit_ack", side_effect=MeterError("full")):
            with self.assertRaises(MeterError):
                self.ack(event)
        self.assertIsNone(self.read()["acknowledgment"])
        ack = self.ack(event)
        with mock.patch.object(self.jobs.events, "_admit_ack", side_effect=MeterError("full")):
            self.assertEqual(ack, self.ack(event))

    def test_insert_failure_rolls_back_ack_transaction(self):
        self.submit()
        event = self.read()["events"][0]
        with self.jobs.ledger.transaction() as db:
            db.execute("CREATE TRIGGER test_ack_failure AFTER INSERT ON job_event_acks "
                       "BEGIN SELECT RAISE(ABORT,'simulated commit failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.ack(event)
        self.assertIsNone(self.read()["acknowledgment"])
        with self.jobs.ledger.transaction() as db:
            db.execute("DROP TRIGGER test_ack_failure")
        self.ack(event)

    def test_ack_tamper_fails_closed_on_read_and_restart(self):
        self.submit()
        self.ack(self.read()["events"][0])
        with self.jobs.ledger.transaction() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM job_event_acks")
        with sqlite3.connect(self.jobs.ledger.db_path) as db:
            db.execute("DROP TRIGGER no_job_ack_update")
            db.execute("UPDATE job_event_acks SET receipt_hash=?", ("f" * 64,))
        with self.assertRaises(MeterError):
            self.read()
        self.jobs.close()
        with self.assertRaises(MeterError):
            JobService(ROOT, directory=self.directory)

    def test_one_sided_history_rollback_leaves_ack_as_evidence_not_permission(self):
        job = self.submit()
        self.jobs.cancel(self.a, job["id"])
        events = self.read()["events"]
        for event in events:
            self.ack(event)
        with sqlite3.connect(self.jobs.ledger.db_path) as db:
            db.execute("DROP TRIGGER no_event_delete")
            db.execute("DELETE FROM events WHERE seq=(SELECT MAX(seq) FROM events)")
            db.execute("UPDATE operations SET state='reserved',failure=NULL")
        with self.assertRaises(MeterError):
            self.read()
        with self.assertRaises(MeterError):
            self.ack(events[0])

    def test_unknown_claim_survives_with_blocker_and_no_handoff_success(self):
        job = self.submit()
        self.jobs.ledger.begin(self.a, job["id"])
        self.restart()
        event = self.read()["events"][-1]
        self.assertEqual(event["status"], "uncertain")
        self.assertEqual(event["blocker"], "execution_outcome_requires_review")
        report = self.jobs.operator_snapshot()
        self.assertTrue(report["paused"])
        self.assertEqual(report["blockers"][0]["job_id"], job["id"])
        proposal = preview_handoff(self.jobs, self.a, event["event_id"], "gas-city")["proposal"]
        self.assertIsNone(proposal["result_manifest_sha256"])
        self.assertFalse(proposal["native_dispatch"])
        self.assertFalse(self.jobs.run_one())
        self.assertEqual(self.jobs.ledger.balance(self.a)["spent_cents"], 0)

    def test_manifest_bound_to_inputs_content_usage_and_stable_after_refund(self):
        job = self.submit()
        self.jobs.run_one()
        before = self.jobs.result_manifest(self.a, job["id"])
        manifest = before["manifest"]
        self.assertEqual(manifest["input_sha256"], object_hash(spec()))
        self.assertEqual(manifest["code_revision"]["value"], job_source_hash(ROOT))
        self.assertEqual(before["manifest_sha256"], object_hash(manifest))
        self.assertIsNone(manifest["model_revision"])
        self.assertGreater(manifest["observed_resources"]["max_rss_kib"], 0)
        self.jobs.refund(self.a, job["id"])
        self.restart()
        self.assertEqual(before, self.jobs.result_manifest(self.a, job["id"]))

    def test_handoff_never_dispatches_and_revalidates_result(self):
        job = self.submit()
        queued = self.read()["events"][0]
        with self.assertRaises(MeterError):
            preview_handoff(self.jobs, self.a, queued["event_id"], "beads")
        self.jobs.run_one()
        done = self.read()["events"][-1]
        for target in TARGETS:
            first = preview_handoff(self.jobs, self.a, done["event_id"], target)
            self.assertEqual(first, preview_handoff(self.jobs, self.a, done["event_id"], target))
            self.assertEqual(first["proposal"]["missing_gates"], list(GATES))
            self.assertFalse(first["proposal"]["native_dispatch"])
        path = Path(self.temp.name) / "results/demo-alpha" / (job["id"] + ".json")
        path.write_text("{}")
        with self.assertRaises(MeterError):
            preview_handoff(self.jobs, self.a, done["event_id"], "beads")

    def test_actual_sigkill_after_ack_commit_preserves_receipt(self):
        self.jobs.close()
        script = (
            "import os,signal,json;from research_commons.job_queue import JobService;"
            "from market_lab.io import ROOT;"
            f"s=JobService(ROOT,directory={self.directory!r});p=s.registry.issue('demo-alpha');"
            f"s.submit(p,'crash-event-0001',json.loads({json.dumps(spec())!r}));"
            "e=s.events.read(p,'research-ui')['events'][0];"
            "a=s.events.acknowledge(p,'research-ui',e['event_id']);print(json.dumps(a),flush=True);"
            "os.kill(os.getpid(),signal.SIGKILL)"
        )
        process = subprocess.run([sys.executable, "-I", "-S", "-B", "-c",
                                  "import sys;sys.path.insert(0," + repr(str(ROOT)) + ");" + script],
                                 capture_output=True, timeout=5)
        self.assertEqual(process.returncode, -signal.SIGKILL)
        prior = json.loads(process.stdout)
        self.restart()
        self.assertEqual(prior, self.jobs.events.acknowledge(self.a, "research-ui", prior["event_id"]))
        self.assertEqual(self.read()["events"], [])
        self.assertEqual(self.jobs.ledger.balance(self.a)["spent_cents"], 0)


class EventHTTPTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "artifacts").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="event-http-", dir=ROOT / "artifacts")
        self.server = JobHTTPServer(directory="artifacts/" + Path(self.temp.name).name, start_worker=False)
        self.token = self.server.issuer.issue("demo-alpha")
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(5)
        self.server.server_close()
        self.temp.cleanup()

    def call(self, route, body=None, *, token=None, method="POST"):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        client.request(method, route, json.dumps(body) if body is not None else None,
                       {"Authorization": "Bearer " + (token or self.token), "Content-Type": "application/json"})
        response = client.getresponse()
        value = response.status, json.loads(response.read())
        client.close()
        return value

    def test_http_read_and_ack_retry_and_tenant_isolation(self):
        _, job = self.call("/v1/jobs", {"key": "http-events-0001", "spec": spec()})
        status, page = self.call("/v1/events/read", {"consumer": "research-ui"})
        self.assertEqual(status, 200)
        body = {"consumer": "research-ui", "event_id": page["events"][0]["event_id"]}
        first = self.call("/v1/events/ack", body)
        self.assertEqual(first, self.call("/v1/events/ack", body))
        beta = self.server.issuer.issue("demo-beta")
        self.assertEqual(self.call("/v1/events/ack", body, token=beta)[0], 409)
        self.server.jobs.run_one()
        self.assertEqual(self.call("/v1/jobs/" + job["id"] + "/manifest", method="GET")[0], 200)
        self.assertEqual(self.call("/v1/jobs/" + job["id"] + "/manifest", method="GET", token=beta)[0], 404)

    def test_http_rejects_credentials_extra_authority_and_operator_route(self):
        self.assertEqual(self.call("/v1/events/read", {"consumer": "research-ui"}, token="forged")[0], 401)
        self.assertEqual(self.call("/v1/events/read", {"consumer": "research-ui", "tenant": "demo-beta"})[0], 400)
        self.assertEqual(self.call("/v1/events/ack", {"consumer": "research-ui", "event_id": "f" * 64,
                                                    "native_dispatch": True})[0], 400)
        self.assertEqual(self.call("/v1/operator", method="GET")[0], 404)

    def test_http_authorized_catalog_and_admission_do_not_submit(self):
        status, catalog = self.call("/v1/catalog", method="GET")
        self.assertEqual(status, 200)
        self.assertEqual(catalog["datasets"][0]["source_kind"], "synthetic")
        status, preview = self.call("/v1/admission", {"spec": spec()})
        self.assertEqual(status, 200)
        self.assertTrue(preview["admitted_now"])
        self.assertFalse(preview["reservation_created"])
        self.assertEqual(self.call("/v1/jobs", method="GET")[1]["jobs"], [])
        self.assertEqual(self.call("/v1/admission", {"spec": spec(), "tenant": "demo-beta"})[0], 400)
        self.assertEqual(self.call("/v1/admission", {"spec": spec()}, token="forged")[0], 401)

    def test_http_sqlite_failure_returns_bounded_retryable_error(self):
        with mock.patch.object(self.server.jobs.events, "acknowledge",
                               side_effect=sqlite3.OperationalError("private storage detail")):
            status, result = self.call("/v1/events/ack", {"consumer": "research-ui", "event_id": "f" * 64})
        self.assertEqual(status, 503)
        self.assertEqual(result, {"error": "storage_unavailable"})


if __name__ == "__main__":
    unittest.main()
