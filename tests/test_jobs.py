"""Real local subprocess/HTTP failures; no public services, accounts or holdout runs."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import errno
import http.client
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from market_lab.io import ROOT, LabError, load_json, object_hash
from research_commons.job_contract import LIMITS, SKU
from research_commons.job_http import JobHTTPServer
from research_commons.job_queue import JobService
from research_commons.ledger import FixtureRegistry, MeterError


def spec():
    return {"submission": load_json(ROOT / "submissions/baseline.json"),
            "split": "development", "resources": dict(LIMITS), "max_price_cents": 50}


def command(code):
    return [sys.executable, "-I", "-S", "-B", "-c",
            "import sys;sys.path.insert(0," + repr(str(ROOT)) + ");" + code]


class JobTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "artifacts").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="jobs-test-", dir=ROOT / "artifacts")
        self.directory = "artifacts/" + Path(self.temp.name).name
        self.service = JobService(ROOT, directory=self.directory)
        self.a = self.service.registry.issue("demo-alpha")
        self.b = self.service.registry.issue("demo-beta")

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def submit(self, key="test-job-0001", principal=None, body=None):
        return self.service.submit(principal or self.a, key, body or spec())

    def restart(self):
        self.service.close()
        self.service = JobService(ROOT, directory=self.directory)
        self.a = self.service.registry.issue("demo-alpha")
        self.b = self.service.registry.issue("demo-beta")

    def test_two_tenants_real_runner_reproducible_results_and_credits(self):
        a = self.submit()
        b = self.submit("test-job-0001", self.b)
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(self.service.ledger.balance(self.a)["held_cents"], 50)
        self.assertTrue(self.service.run_one())
        self.assertTrue(self.service.run_one())
        first = self.service.result(self.a, a["id"])
        second = self.service.result(self.b, b["id"])
        self.assertEqual(first, second)
        self.assertEqual(first["provenance"]["split"], "development")
        self.assertEqual(self.service.get(self.a, a["id"])["charged_cents"], 50)
        self.assertEqual(self.service.ledger.balance(self.a)["available_cents"], 150)
        self.assertEqual([x["state"] for x in self.service.history(self.a, a["id"])],
                         ["reserved", "executing", "settled"])

    def test_cross_tenant_job_result_history_cancel_and_credit_isolation(self):
        a = self.submit()
        self.service.run_one()
        for method in (self.service.get, self.service.result, self.service.history,
                       self.service.cancel, self.service.refund):
            with self.subTest(method=method.__name__), self.assertRaises(MeterError):
                method(self.b, a["id"])
        self.assertEqual(self.service.listing(self.b), [])
        self.assertEqual(self.service.ledger.balance(self.b)["available_cents"], 200)

    def test_concurrent_duplicates_create_one_job_and_one_charge(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            receipts = list(executor.map(lambda _: self.submit(), range(16)))
        self.assertEqual(len({r["id"] for r in receipts}), 1)
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: self.service.run_one(), range(4)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.service.ledger.balance(self.a)["spent_cents"], 50)
        changed = spec()
        changed["max_price_cents"] = 100
        with self.assertRaisesRegex(MeterError, "different request"):
            self.submit(body=changed)

    def test_concurrent_admission_cannot_overspend_or_overfill(self):
        def send(index):
            try:
                return self.submit(f"distinct-job-{index:04d}")
            except MeterError:
                return None
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(send, range(20)))
        self.assertEqual(sum(bool(r) for r in results), 2)
        for _ in range(2):
            self.service.run_one()
        for i in range(2):
            self.submit(f"spend-rest-{i:04d}")
            self.service.run_one()
        with self.assertRaisesRegex(MeterError, "budget"):
            self.submit("over-budget-0001")
        self.assertEqual(self.service.ledger.balance(self.a)["spent_cents"], 200)

    def test_queue_and_exact_id_survive_restart_without_reexecution(self):
        first = self.submit()
        self.restart()
        self.assertEqual(self.submit()["id"], first["id"])
        self.service.run_one()
        self.restart()
        self.assertEqual(self.submit()["status"], "succeeded")
        self.assertFalse(self.service.run_one())
        self.assertEqual(self.service.ledger.balance(self.a)["spent_cents"], 50)

    def test_uncertain_claim_never_replays_and_pauses_all_admission(self):
        first = self.submit()
        self.service.ledger.begin(self.a, first["id"])
        self.restart()
        self.assertEqual(self.submit()["status"], "uncertain")
        self.assertFalse(self.service.run_one())
        with self.assertRaises(MeterError):
            self.submit("new-after-uncertain")
        with self.assertRaises(MeterError):
            self.service.resume()
        self.assertEqual(self.service.ledger.balance(self.a)["spent_cents"], 0)

    def test_cancel_before_start_is_durable_and_never_executes(self):
        first = self.submit()
        self.service.cancel(self.a, first["id"])
        self.restart()
        self.assertFalse(self.service.run_one())
        self.assertEqual(self.submit()["status"], "cancelled")
        self.assertEqual(self.service.ledger.balance(self.a)["held_cents"], 0)

    def test_running_cancel_releases_credit_only_after_process_exit(self):
        first = self.submit()
        script = "import time;sys.stdin.buffer.read();time.sleep(30)"
        with mock.patch.object(self.service, "_command", return_value=command(script)):
            thread = threading.Thread(target=self.service.run_one)
            thread.start()
            deadline = time.monotonic() + 3
            while self.service.get(self.a, first["id"])["status"] != "running":
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
            result = self.service.cancel(self.a, first["id"])
            self.assertEqual(result["status"], "cancelling")
            thread.join(5)
            self.assertFalse(thread.is_alive())
        result = self.service.get(self.a, first["id"])
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["failure"], "worker_exit_confirmed")
        self.assertEqual(result["charged_cents"], 0)

    def test_worker_failure_wall_and_output_overuse_are_terminal(self):
        cases = (
            ("exit", "sys.stdin.buffer.read();sys.exit(9)", "worker_failed_or_resource_limit"),
            ("wall", "import time;sys.stdin.buffer.read();time.sleep(30)", "wall_limit_exceeded"),
            ("output", "sys.stdin.buffer.read();sys.stdout.write('x'*600000)", "output_limit_exceeded"),
        )
        for name, script, reason in cases:
            with self.subTest(name=name):
                body = spec()
                body["resources"]["wall_seconds"] = 1
                receipt = self.submit("failed-worker-" + name, body=body)
                with mock.patch.object(self.service, "_command", return_value=command(script)):
                    self.service.run_one()
                result = self.service.get(self.a, receipt["id"])
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["failure"], reason)
                self.assertEqual(result["charged_cents"], 0)
        self.assertFalse(self.service.run_one())

    def test_invalid_contracts_holdout_and_resource_escalation_rejected(self):
        variants = []
        for key, value in (("split", "holdout"), ("max_price_cents", 49),
                           ("tenant", "demo-beta"), ("command", "anything")):
            body = spec(); body[key] = value; variants.append(body)
        for resource, value in (("gpu", 1), ("memory_mib", 257), ("cpu_seconds", True),
                                ("wall_seconds", 11), ("output_bytes", 524289)):
            body = spec(); body["resources"][resource] = value; variants.append(body)
        body = spec(); body["submission"]["strategy"]["name"] = "user_python"; variants.append(body)
        for body in variants:
            with self.subTest(body=body.get("split")), self.assertRaises(LabError):
                self.submit(body=body)
        self.assertEqual(self.service.ledger.balance(self.a)["operations"], 0)

    def test_dataset_entitlement_cannot_be_chosen_by_requester(self):
        self.service.entitlements["demo-beta"] = set()
        with self.assertRaisesRegex(MeterError, "entitled"):
            self.submit(principal=self.b)
        first = self.submit()
        self.service.entitlements["demo-alpha"] = set()
        self.service.run_one()
        self.assertEqual(self.service.get(self.a, first["id"])["status"], "cancelled")

    def test_fairness_uses_durable_tenant_service_history(self):
        a1 = self.submit("alpha-first-0001")
        self.service.run_one()
        a2 = self.submit("alpha-next-0001")
        b1 = self.submit("beta-next-0001", self.b)
        self.restart()
        self.service.run_one()
        self.assertEqual(self.service.get(self.b, b1["id"])["status"], "succeeded")
        self.assertEqual(self.service.get(self.a, a2["id"])["status"], "queued")

    def test_corrupted_result_fails_closed_on_read_and_restart(self):
        first = self.submit()
        self.service.run_one()
        result_path = Path(self.temp.name) / "results/demo-alpha" / (first["id"] + ".json")
        result_path.write_text("{}")
        with self.assertRaisesRegex(MeterError, "digest"):
            self.service.result(self.a, first["id"])
        self.service.close()
        with self.assertRaisesRegex(MeterError, "digest"):
            JobService(ROOT, directory=self.directory)

    def test_corrupted_request_or_result_projection_fails_audit(self):
        first = self.submit()
        with sqlite3.connect(self.service.ledger.db_path) as db:
            db.execute("UPDATE operations SET params='{}' WHERE id=?", (first["id"],))
        with self.assertRaisesRegex(MeterError, "audit"):
            self.service.get(self.a, first["id"])

    def test_aggregate_disk_floor_and_pause_stop_admission(self):
        with mock.patch("research_commons.job_queue.shutil.disk_usage", return_value=shutil_usage(0)):
            with self.assertRaisesRegex(MeterError, "storage"):
                self.submit()
        self.service.pause()
        self.restart()
        with self.assertRaisesRegex(MeterError, "paused"):
            self.submit()
        self.service.resume()
        self.submit()

    def test_refund_preserves_result_and_restores_synthetic_credit_once(self):
        first = self.submit()
        self.service.run_one()
        report = self.service.result(self.a, first["id"])
        self.service.refund(self.a, first["id"])
        self.service.refund(self.a, first["id"])
        self.assertEqual(self.service.ledger.balance(self.a)["available_cents"], 200)
        self.assertEqual(self.service.result(self.a, first["id"]), report)

    def test_second_controller_cannot_acquire_ledger(self):
        with self.assertRaises(BlockingIOError):
            JobService(ROOT, directory=self.directory)

    def test_sigkill_after_durable_claim_recovers_uncertain_without_replay(self):
        self.service.close()
        script = (
            "import os,signal,json;from research_commons.job_queue import JobService;"
            "from market_lab.io import ROOT;"
            f"s=JobService(ROOT,directory={self.directory!r});"
            "p=s.registry.issue('demo-alpha');"
            f"r=s.submit(p,'actual-crash-0001',json.loads({json.dumps(spec())!r}));"
            "s.ledger.begin(p,r['id']);print(r['id'],flush=True);os.kill(os.getpid(),signal.SIGKILL)"
        )
        killed = subprocess.run(command(script), capture_output=True, timeout=5)
        self.assertEqual(killed.returncode, -signal.SIGKILL)
        job_id = killed.stdout.decode().strip()
        self.restart()
        self.assertEqual(self.service.get(self.a, job_id)["status"], "uncertain")
        self.assertFalse(self.service.run_one())
        self.assertEqual(self.service.ledger.balance(self.a)["available_cents"], 200)

    def test_sigkill_between_artifact_and_settlement_preserves_orphan(self):
        self.service.close()
        script = (
            "import os,signal,json;from research_commons.job_queue import JobService;"
            "from market_lab.io import ROOT;"
            f"s=JobService(ROOT,directory={self.directory!r});"
            "p=s.registry.issue('demo-alpha');"
            f"r=s.submit(p,'artifact-crash-0001',json.loads({json.dumps(spec())!r}));"
            "print(r['id'],flush=True);"
            "s.ledger.finish=lambda *args,**kwargs:os.kill(os.getpid(),signal.SIGKILL);s.run_one()"
        )
        killed = subprocess.run(command(script), capture_output=True, timeout=5)
        self.assertEqual(killed.returncode, -signal.SIGKILL)
        job_id = killed.stdout.decode().strip()
        retained = Path(self.temp.name) / "results/demo-alpha" / (job_id + ".json")
        self.assertTrue(retained.is_file())
        before = retained.read_bytes()
        self.restart()
        self.assertEqual(self.service.get(self.a, job_id)["status"], "uncertain")
        self.assertFalse(self.service.run_one())
        self.assertEqual(before, retained.read_bytes())
        with self.assertRaises(MeterError):
            self.service.result(self.a, job_id)


def shutil_usage(free):
    from collections import namedtuple
    return namedtuple("usage", "total used free")(1000000000, 100000, free)


@unittest.skipUnless(sys.platform == "linux", "kernel controls require Linux")
class KernelIsolationTests(unittest.TestCase):
    def probe(self, script):
        prefix = (
            "import os,socket,resource,time;"
            "from research_commons.job_limits import install_limits;"
            "from research_commons.job_contract import LIMITS;"
            "limits=dict(LIMITS);limits['cpu_seconds']=1;"
            "install_limits(limits,os.getppid());"
        )
        return subprocess.run(command(prefix + script), capture_output=True, timeout=5,
                              env={"LC_ALL": "C.UTF-8"}, close_fds=True)

    def test_kernel_denies_network_filesystem_and_subprocess_creation(self):
        probes = ("socket.socket()", "open('/etc/hostname').read()", "os.fork()")
        for script in probes:
            with self.subTest(script=script):
                result = self.probe(script)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"Operation not permitted", result.stderr)

    def test_kernel_memory_and_cpu_limits(self):
        memory = self.probe("bytearray(512*1024*1024)")
        self.assertNotEqual(memory.returncode, 0)
        self.assertIn(b"MemoryError", memory.stderr)
        cpu = self.probe("exec('while True: pass')")
        self.assertEqual(cpu.returncode, -signal.SIGKILL)

    def test_parent_death_fence_stops_a_running_worker(self):
        child_code = (
            "import os,time;from research_commons.job_limits import install_limits;"
            "from research_commons.job_contract import LIMITS;"
            "install_limits(LIMITS,os.getppid());print('READY',flush=True);time.sleep(30)"
        )
        parent = (
            "import subprocess,os,signal;"
            f"p=subprocess.Popen({command(child_code)!r},stdout=subprocess.PIPE);"
            "assert p.stdout.readline()==b'READY\\n';print(p.pid,flush=True);"
            "os.kill(os.getpid(),signal.SIGKILL)"
        )
        killed = subprocess.run(command(parent), capture_output=True, timeout=5)
        self.assertEqual(killed.returncode, -signal.SIGKILL)
        child_pid = int(killed.stdout)
        deadline = time.monotonic() + 2
        while True:
            try:
                state = Path(f"/proc/{child_pid}/stat").read_text().split(") ", 1)[1].split()[0]
            except (FileNotFoundError, ProcessLookupError):
                break
            if state == "Z":
                break
            self.assertLess(time.monotonic(), deadline, "child still running after controller SIGKILL")
            time.sleep(.02)


class JobHTTPTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "artifacts").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="job-http-", dir=ROOT / "artifacts")
        self.directory = "artifacts/" + Path(self.temp.name).name
        self.http = JobHTTPServer(directory=self.directory)
        self.a = self.http.issuer.issue("demo-alpha")
        self.b = self.http.issuer.issue("demo-beta")
        self.thread = threading.Thread(target=self.http.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown(); self.thread.join(5); self.http.server_close()
        self.temp.cleanup()

    def request(self, method, path, body=None, token=None, extra=None):
        client = http.client.HTTPConnection("127.0.0.1", self.http.server_port, timeout=5)
        headers = {"Authorization": "Bearer " + (token or self.a), "Content-Type": "application/json"}
        headers.update(extra or {})
        client.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = client.getresponse()
        result = response.status, json.loads(response.read())
        client.close()
        return result

    def test_http_event_trigger_runs_job_without_followup_prompt(self):
        status, receipt = self.request("POST", "/v1/jobs", {"key": "http-job-0001", "spec": spec()})
        self.assertEqual(status, 202)
        deadline = time.monotonic() + 5
        while True:
            status, result = self.request("GET", "/v1/jobs/" + receipt["id"])
            if result["status"] == "succeeded":
                break
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.02)
        for suffix in ("", "/history", "/result"):
            self.assertEqual(self.request("GET", "/v1/jobs/" + receipt["id"] + suffix, token=self.b)[0], 404)
        self.assertEqual(self.request("GET", "/v1/credits", token=self.b)[1]["spent_cents"], 0)
        self.assertEqual(self.request("GET", "/v1/jobs", token=self.b)[1]["jobs"], [])

    def test_expired_revoked_and_previous_boot_tokens_are_rejected(self):
        revoked = self.http.issuer.issue("demo-alpha")
        self.http.issuer.revoke_token(revoked)
        expired = self.http.issuer.issue("demo-alpha", overrides={"exp": 1})
        from research_commons.sandbox_identity import DevTokenIssuer
        old_boot = DevTokenIssuer().issue("demo-alpha")
        for token in (revoked, expired, old_boot, "forged"):
            self.assertEqual(self.request("GET", "/v1/jobs", token=token)[0], 401)

    def test_host_origin_and_tenant_injection_fail(self):
        for headers in ({"Host": "evil.invalid"}, {"Origin": "https://evil.invalid"}):
            self.assertEqual(self.request("GET", "/v1/jobs", extra=headers)[0], 401)
        self.assertEqual(self.request("POST", "/v1/jobs",
                                     {"key": "http-job-0001", "spec": spec(), "tenant": "demo-beta"})[0], 400)

    def test_simultaneous_http_tenants_do_not_share_idempotency_namespace(self):
        def submit(token):
            return self.request("POST", "/v1/jobs", {"key": "same-http-key", "spec": spec()}, token=token)
        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = list(executor.map(submit, [self.a, self.a, self.b, self.b]))
        self.assertTrue(all(status == 202 for status, _ in responses))
        self.assertEqual(responses[0][1]["id"], responses[1][1]["id"])
        self.assertEqual(responses[2][1]["id"], responses[3][1]["id"])
        self.assertNotEqual(responses[0][1]["id"], responses[2][1]["id"])


if __name__ == "__main__":
    unittest.main()
