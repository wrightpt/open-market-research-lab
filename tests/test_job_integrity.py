"""Detected partial-history faults must never revive work or settle usage."""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from market_lab.io import ROOT, load_json, write_new
from research_commons.job_contract import LIMITS
from research_commons.job_queue import JobService
from research_commons.ledger import MeterError


def spec():
    return {"submission": load_json(ROOT / "submissions/baseline.json"),
            "split": "development", "resources": dict(LIMITS), "max_price_cents": 50}


class IntegrityFenceTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "artifacts").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="job-integrity-", dir=ROOT / "artifacts")
        self.directory = "artifacts/" + Path(self.temp.name).name
        self.jobs = JobService(ROOT, directory=self.directory, clock=lambda: 100.0)
        self.a = self.jobs.registry.issue("demo-alpha")

    def tearDown(self):
        self.jobs.close()
        self.temp.cleanup()

    def submit(self):
        return self.jobs.submit(self.a, "integrity-job-0001", spec())

    def acknowledge_all(self):
        for event in self.jobs.events.read(self.a, "research-ui")["events"]:
            self.jobs.events.acknowledge(self.a, "research-ui", event["event_id"])

    def snapshot(self):
        with closing(sqlite3.connect(self.jobs.ledger.db_path)) as db:
            return {name: db.execute("SELECT * FROM " + name + " ORDER BY rowid").fetchall()
                    for name in ("operations", "events", "job_event_acks")}

    def corrupt_ack(self):
        # Fault only this test's disposable synthetic ledger, never a live store.
        with closing(sqlite3.connect(self.jobs.ledger.db_path)) as db, db:
            db.execute("DROP TRIGGER no_job_ack_update")
            db.execute("UPDATE job_event_acks SET receipt_hash=?", ("f" * 64,))

    def rollback_history(self):
        # Preserve ACKs and any result. Rewind only job history, as in R1.
        with closing(sqlite3.connect(self.jobs.ledger.db_path)) as db, db:
            db.execute("DROP TRIGGER no_event_delete")
            db.execute("DELETE FROM events WHERE seq > (SELECT MIN(seq) FROM events)")
            db.execute("UPDATE operations SET state='reserved',failure=NULL,"
                       "result_hash=NULL,result_json=NULL")

    def assert_fenced(self, job):
        before = self.snapshot()
        actions = (
            lambda: self.jobs.events.read(self.a, "research-ui"),
            lambda: self.jobs.preflight(self.a, spec()),
            lambda: self.jobs.submit(self.a, "integrity-job-new", spec()),
            self.submit,
            lambda: self.jobs.ledger.begin(self.a, job["id"]),
            lambda: self.jobs.cancel(self.a, job["id"]),
            self.jobs.resume,
            self.jobs.run_one,
        )
        with mock.patch("research_commons.job_queue.subprocess.Popen") as launch:
            for action in actions:
                with self.subTest(action=action), self.assertRaises(MeterError):
                    action()
            launch.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        health = self.jobs.health()
        self.assertTrue(health["paused"])
        self.assertIsNotNone(health["controller_error"])
        with closing(sqlite3.connect(self.jobs.ledger.db_path)) as db:
            self.assertEqual(db.execute("SELECT paused FROM job_control").fetchone()[0], 1)

    def test_cancelled_history_cannot_be_admitted_claimed_or_charged_again(self):
        job = self.submit()
        self.jobs.cancel(self.a, job["id"])
        self.acknowledge_all()
        self.rollback_history()
        self.assert_fenced(job)

    def test_completed_history_cannot_launch_again_and_retains_result(self):
        job = self.submit()
        self.assertTrue(self.jobs.run_one())
        self.acknowledge_all()
        result = Path(self.temp.name) / "results/demo-alpha" / (job["id"] + ".json")
        retained = hashlib.sha256(result.read_bytes()).hexdigest()
        self.rollback_history()
        self.assert_fenced(job)
        self.assertEqual(hashlib.sha256(result.read_bytes()).hexdigest(), retained)

    def test_controller_detects_corruption_without_an_event_reader(self):
        self.submit()
        self.acknowledge_all()
        self.corrupt_ack()
        before = self.snapshot()
        with mock.patch("research_commons.job_queue.subprocess.Popen") as launch:
            with self.assertRaises(MeterError):
                self.jobs.run_one()
            launch.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.jobs.health()["paused"])

    def test_startup_verifies_ack_before_expiry_or_uncertain_reconciliation(self):
        job = self.submit()
        self.acknowledge_all()
        self.jobs.ledger.begin(self.a, job["id"])
        self.corrupt_ack()
        before = self.snapshot()
        self.jobs.close()
        with self.assertRaises(MeterError):
            JobService(ROOT, directory=self.directory, clock=lambda: 1000.0)
        self.assertEqual(self.snapshot(), before)

    def test_fault_after_claim_is_checked_before_worker_launch(self):
        self.submit()
        self.acknowledge_all()
        item = self.jobs._next()
        self.corrupt_ack()
        before = self.snapshot()
        with mock.patch("research_commons.job_queue.subprocess.Popen") as launch:
            with self.assertRaises(MeterError):
                self.jobs._execute(item)
            launch.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.jobs.health()["paused"])

    def test_fault_after_result_write_cannot_settle_or_erase_evidence(self):
        job = self.submit()
        self.acknowledge_all()
        def write_and_fault(*args, **kwargs):
            value = write_new(*args, **kwargs)
            self.corrupt_ack()
            return value
        with mock.patch("research_commons.job_queue.write_new", side_effect=write_and_fault):
            with self.assertRaises(MeterError):
                self.jobs.run_one()
        with closing(sqlite3.connect(self.jobs.ledger.db_path)) as db:
            self.assertEqual(db.execute("SELECT state FROM operations").fetchone()[0], "executing")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 2)
        self.assertTrue((Path(self.temp.name) / "results/demo-alpha" / (job["id"] + ".json")).is_file())
        self.assertTrue(self.jobs.health()["paused"])

    def test_expired_reservation_is_preserved_when_startup_evidence_disagrees(self):
        self.submit()
        self.acknowledge_all()
        self.corrupt_ack()
        before = self.snapshot()
        self.jobs.close()
        with self.assertRaises(MeterError):
            JobService(ROOT, directory=self.directory, clock=lambda: 1000.0)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
