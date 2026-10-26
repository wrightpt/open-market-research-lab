"""Independent review regressions for worker startup and controller failures.

These inject bounded local worker faults; they do not run executable user
strategies or make network connections. Every injected child is reaped in
cleanup even when the assertion exposes a containment regression.
"""
import fcntl
import sqlite3
import subprocess
import threading
import unittest
from unittest import mock

from tests import test_jobs

command = test_jobs.command
spec = test_jobs.spec


class WorkerBoundaryReview(unittest.TestCase):
    setUp = test_jobs.JobTests.setUp
    tearDown = test_jobs.JobTests.tearDown
    submit = test_jobs.JobTests.submit

    @staticmethod
    def reap(children):
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=3)

    def _check_startup_backpressure(self, cancel=False):
        body = spec()
        body["submission"]["hypothesis"] = "\u2603" * 1200
        body["resources"]["wall_seconds"] = 10 if cancel else 1
        job = self.submit(body=body)
        children = []
        started = threading.Event()
        real_popen = subprocess.Popen

        def small_pipe(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            # A valid Linux pipe size; reproduce a resource-constrained host
            # without changing host configuration or affecting other processes.
            fcntl.fcntl(child.stdin.fileno(), fcntl.F_SETPIPE_SZ, 4096)
            children.append(child)
            started.set()
            return child

        errors = []

        def run():
            try:
                self.service.run_one()
            except BaseException as exc:
                errors.append(exc)

        with mock.patch.object(self.service, "_command", return_value=command("import time;time.sleep(30)")), \
             mock.patch("research_commons.job_queue.subprocess.Popen", side_effect=small_pipe):
            thread = threading.Thread(target=run)
            try:
                thread.start()
                self.assertTrue(started.wait(2))
                if cancel:
                    self.service.cancel(self.a, job["id"])
                thread.join(2)
                bounded = not thread.is_alive()
            finally:
                self.reap(children)
                thread.join(3)
        self.assertTrue(bounded, "blocking stdin delivery bypassed deadline or cancellation")
        self.assertFalse(errors, errors)
        self.assertEqual(self.service.get(self.a, job["id"])["status"],
                         "cancelled" if cancel else "failed")

    def test_startup_backpressure_obeys_deadline(self):
        """Linux pipes may be smaller than an admitted request; writes must yield."""
        self._check_startup_backpressure()

    def test_startup_backpressure_obeys_cancellation(self):
        self._check_startup_backpressure(cancel=True)

    def test_unexpected_controller_error_reaps_existing_worker(self):
        """A SQLite error must not leave an executing child after run_one exits."""
        job = self.submit()
        children = []
        real_popen = subprocess.Popen
        real_get = self.service.ledger.get

        def record(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        fail_once = True

        def fail_running_read(*args, **kwargs):
            nonlocal fail_once
            if children and fail_once:
                fail_once = False
                raise sqlite3.OperationalError("injected worker-monitor database failure")
            return real_get(*args, **kwargs)

        with mock.patch.object(self.service, "_command", return_value=command(
                "import time;sys.stdin.buffer.read();time.sleep(30)")), \
             mock.patch("research_commons.job_queue.subprocess.Popen", side_effect=record), \
             mock.patch.object(self.service.ledger, "get", side_effect=fail_running_read):
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    self.service.run_one()
                self.assertTrue(children)
                still_running = children[0].poll() is None
            finally:
                self.reap(children)
        self.assertFalse(still_running, "controller exited without terminating its worker")
        self.assertTrue(self.service.health()["paused"])
        self.assertEqual(self.service.get(self.a, job["id"])["charged_cents"], 0)

    def test_close_waits_for_external_run_one_before_unlocking_ledger(self):
        """The public synchronous runner owns the same fence as start()'s thread."""
        self.submit()
        execution_entered = threading.Event()
        execution_release = threading.Event()
        close_entered = threading.Event()
        close_done = threading.Event()
        errors = []

        def blocked_execution(item):
            execution_entered.set()
            if not execution_release.wait(4):
                raise RuntimeError("review test cleanup did not release the runner")

        def run():
            try:
                self.service.run_one()
            except BaseException as exc:
                errors.append(exc)

        def close():
            close_entered.set()
            try:
                self.service.close()
            except BaseException as exc:
                errors.append(exc)
            finally:
                close_done.set()

        with mock.patch.object(self.service, "_execute", side_effect=blocked_execution):
            runner = threading.Thread(target=run)
            closer = threading.Thread(target=close)
            try:
                runner.start()
                self.assertTrue(execution_entered.wait(2))
                closer.start()
                self.assertTrue(close_entered.wait(2))
                closed_while_running = close_done.wait(.2)
                lock_was_held = False
                replacement = None
                try:
                    replacement = test_jobs.JobService(test_jobs.ROOT, directory=self.directory)
                except BlockingIOError:
                    lock_was_held = True
                finally:
                    if replacement is not None:
                        replacement.close()
            finally:
                execution_release.set()
                runner.join(3)
                closer.join(3)
        self.assertFalse(closed_while_running, "close returned while public run_one was active")
        self.assertTrue(lock_was_held, "close released controller authority before the runner exited")
        self.assertFalse(errors, errors)

    def test_corrupted_failure_explanation_is_rejected(self):
        job = self.submit()
        self.service.cancel(self.a, job["id"])
        with self.service.ledger.transaction() as db:
            db.execute("UPDATE operations SET failure=? WHERE id=?",
                       ("corrupted explanation", job["id"]))
        with self.assertRaises(test_jobs.MeterError):
            self.service.get(self.a, job["id"])

    def test_corrupted_credit_budget_is_rejected_before_admission(self):
        with self.service.ledger.transaction() as db:
            db.execute("UPDATE tenants SET budget_cents=999 WHERE tenant_id=?",
                       (self.a.tenant_id,))
        with self.assertRaises(test_jobs.MeterError):
            self.service.ledger.balance(self.a)
        with self.assertRaises(test_jobs.MeterError):
            self.submit()

    def test_compact_worker_reply_cannot_expand_past_artifact_ceiling(self):
        """Account for stored canonical bytes, not only wire representation."""
        job = self.submit()
        script = (
            "import json;"
            "from market_lab.io import ROOT,object_hash;"
            "from market_lab.data import manifest,load_split;"
            "from market_lab.research import build_report;"
            "q=json.load(sys.stdin);s=q['spec'];m=manifest(ROOT);"
            "r=build_report(ROOT,s['submission'],m,'development',load_split(ROOT,'development',m));"
            "r['padding']=[0]*110000;h=object_hash(r);"
            "e={'network':'kernel_denied','filesystem_open':'kernel_denied',"
            "'child_processes':'kernel_denied','cpu_affinity_cores':1,"
            "'parent_death':'SIGKILL','limits':s['resources']};"
            "a={'report':r,'report_sha256':h,'replay_sha256':h,'enforcement':e,"
            "'cpu_seconds':0.1,'max_rss_kib':1024};"
            "raw=json.dumps(a,separators=(',',':'));"
            "assert len(raw.encode()) < s['resources']['output_bytes'];"
            "sys.stdout.write(raw)"
        )
        with mock.patch.object(self.service, "_command", return_value=command(script)):
            self.service.run_one()
        receipt = self.service.get(self.a, job["id"])
        path = test_jobs.ROOT / self.directory / "results" / self.a.tenant_id / (job["id"] + ".json")
        stored_size = path.stat().st_size if path.exists() else 0
        self.assertLessEqual(stored_size, spec()["resources"]["output_bytes"])
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["charged_cents"], 0)

    def test_closed_ledger_cannot_resume_writes_after_replacement_opens(self):
        job = self.submit()
        self.service.close()
        replacement = test_jobs.JobService(test_jobs.ROOT, directory=self.directory)
        try:
            with self.assertRaisesRegex(test_jobs.MeterError, "closed"):
                with self.service.ledger.transaction() as db:
                    db.execute("UPDATE operations SET state='cancelled' WHERE id=?", (job["id"],))
            principal = replacement.registry.issue("demo-alpha")
            self.assertEqual(replacement.get(principal, job["id"])["status"], "queued")
        finally:
            replacement.close()

    def test_package_initializer_is_bound_by_frozen_source_identity(self):
        from research_commons import job_contract
        original = job_contract.job_source_hash(test_jobs.ROOT)
        real_read = job_contract.read_bytes

        def changed_initializer(path, limit):
            content = real_read(path, limit)
            if path.name == "__init__.py" and path.parent.name == "research_commons":
                return content + b"\n# simulated executable initializer drift\n"
            return content

        with mock.patch.object(job_contract, "read_bytes", side_effect=changed_initializer):
            self.assertNotEqual(original, job_contract.job_source_hash(test_jobs.ROOT))


if __name__ == "__main__":
    unittest.main()
