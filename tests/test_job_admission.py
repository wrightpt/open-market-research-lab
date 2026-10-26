"""Admission previews confer no reservation, data rights or payment authority."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from market_lab.io import ROOT, LabError, load_json, object_hash
from research_commons.job_contract import LIMITS
from research_commons.job_queue import JobService
from research_commons.ledger import FixtureRegistry, MeterError


def spec():
    return {"submission": load_json(ROOT / "submissions/baseline.json"),
            "split": "development", "resources": dict(LIMITS), "max_price_cents": 50}


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "artifacts").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="job-admission-", dir=ROOT / "artifacts")
        self.directory = "artifacts/" + Path(self.temp.name).name
        self.registry = FixtureRegistry({f"tenant-{i}": 200 for i in range(8)})
        self.jobs = JobService(ROOT, directory=self.directory, registry=self.registry)
        self.people = [self.registry.issue(f"tenant-{i}") for i in range(8)]
        self.a = self.people[0]

    def tearDown(self):
        self.jobs.close()
        self.temp.cleanup()

    def test_catalog_is_tenant_authorized_synthetic_and_read_only(self):
        catalog = self.jobs.authorized_catalog(self.a)
        self.assertEqual(len(catalog["datasets"]), 1)
        self.assertEqual(catalog["datasets"][0]["source_kind"], "synthetic")
        self.assertEqual(catalog["datasets"][0]["split"], "development")
        self.assertEqual(self.jobs.ledger.balance(self.a)["operations"], 0)
        self.jobs.entitlements["tenant-0"] = set()
        self.assertEqual(self.jobs.authorized_catalog(self.a)["datasets"], [])
        self.assertEqual(self.jobs.authorized_catalog(self.a)["strategies"], [])
        with self.assertRaises(MeterError):
            self.jobs.preflight(self.a, spec())
        self.assertEqual(len(self.jobs.authorized_catalog(self.people[1])["datasets"]), 1)

    def test_preview_retries_do_not_reserve_or_charge(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            previews = list(pool.map(lambda _: self.jobs.preflight(self.a, spec()), range(16)))
        self.assertTrue(all(p["admitted_now"] for p in previews))
        self.assertTrue(all(not p["reservation_created"] for p in previews))
        self.assertEqual(self.jobs.ledger.balance(self.a)["operations"], 0)
        self.assertEqual(self.jobs.events.read(self.a, "research-ui")["events"], [])
        self.assertEqual(previews[0]["policy_sha256"], object_hash(previews[0]["policy"]))

    def test_global_eight_reservations_and_no_future_capacity_guarantee(self):
        preview = self.jobs.preflight(self.a, spec())
        self.assertTrue(preview["admitted_now"])
        originals = [self.jobs.submit(p, "global-job-0001", spec()) for p in self.people]
        denied = self.jobs.preflight(self.a, spec())
        self.assertFalse(denied["admitted_now"])
        self.assertIn("aggregate_resource_or_storage_admission_exhausted", denied["blockers"])
        with self.assertRaises(MeterError):
            self.jobs.submit(self.a, "global-job-0002", spec())
        self.assertEqual(self.jobs.submit(self.a, "global-job-0001", spec())["id"], originals[0]["id"])
        self.jobs.cancel(self.people[-1], originals[-1]["id"])
        self.assertTrue(self.jobs.preflight(self.a, spec())["admitted_now"])

    def test_concurrent_distinct_submissions_respect_global_limit(self):
        def submit(i):
            try:
                return self.jobs.submit(self.people[i % 8], f"concurrent-{i:04d}", spec())
            except MeterError:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            accepted = [r for r in pool.map(submit, range(32)) if r]
        self.assertEqual(len(accepted), 8)
        self.assertEqual(sum(self.jobs.ledger.balance(p)["held_cents"] for p in self.people), 400)
        self.assertEqual(sum(self.jobs.ledger.balance(p)["spent_cents"] for p in self.people), 0)
        self.assertTrue(all(self.jobs.ledger.balance(p)["active"] <= 2 for p in self.people))

    def test_tenant_limit_cancel_and_read_replay_cannot_change_metering(self):
        jobs = [self.jobs.submit(self.a, f"tenant-job-{i:04d}", spec()) for i in range(2)]
        preview = self.jobs.preflight(self.a, spec())
        self.assertIn("tenant_active_limit", preview["blockers"])
        before = self.jobs.ledger.balance(self.a)
        page = self.jobs.events.read(self.a, "research-ui")
        for event in page["events"]:
            self.jobs.events.acknowledge(self.a, "research-ui", event["event_id"])
            self.jobs.events.acknowledge(self.a, "research-ui", event["event_id"])
        self.assertEqual(before, self.jobs.ledger.balance(self.a))
        self.jobs.cancel(self.a, jobs[0]["id"])
        self.assertTrue(self.jobs.preflight(self.a, spec())["admitted_now"])
        self.assertEqual(self.jobs.ledger.balance(self.a)["spent_cents"], 0)

    def test_exhausted_budget_blocks_new_work_but_not_original_receipt(self):
        first = None
        for i in range(4):
            job = self.jobs.submit(self.a, f"spend-job-{i:04d}", spec())
            first = first or job
            self.jobs.run_one()
        preview = self.jobs.preflight(self.a, spec())
        self.assertEqual(preview["blockers"], ["insufficient_simulated_budget"])
        self.assertEqual(self.jobs.submit(self.a, "spend-job-0000", spec())["id"], first["id"])
        with self.assertRaises(MeterError):
            self.jobs.submit(self.a, "spend-job-next", spec())
        self.assertEqual(self.jobs.ledger.balance(self.a)["spent_cents"], 200)

    def test_source_entitlement_and_price_are_rechecked_after_preview(self):
        self.assertTrue(self.jobs.preflight(self.a, spec())["admitted_now"])
        self.jobs.entitlements["tenant-0"] = set()
        with self.assertRaises(MeterError):
            self.jobs.submit(self.a, "revoked-after-preview", spec())
        self.jobs.entitlements["tenant-0"] = {"synthetic-liquidity-v1"}
        modified = spec()
        modified["max_price_cents"] = 49
        with self.assertRaises(LabError):
            self.jobs.preflight(self.a, modified)
        self.assertEqual(self.jobs.ledger.balance(self.a)["operations"], 0)

    def test_external_dataset_holdout_and_authority_injection_rejected(self):
        variants = []
        for key, value in (("split", "holdout"), ("dataset_url", "https://example.invalid/data"),
                           ("real_payments", True), ("native_dispatch", True),
                           ("tenant", "tenant-1")):
            body = spec(); body[key] = value; variants.append(body)
        other = spec(); other["submission"]["dataset"]["id"] = "quant-market-live"; variants.append(other)
        bad_hash = deepcopy(spec()); bad_hash["submission"]["dataset"]["development_sha256"] = "f" * 64
        variants.append(bad_hash)
        for body in variants:
            with self.subTest(keys=list(body)), self.assertRaises(LabError):
                self.jobs.preflight(self.a, body)
        self.assertEqual(self.jobs.ledger.balance(self.a)["operations"], 0)

    def test_preview_paused_recovery_never_grants_admission(self):
        job = self.jobs.submit(self.a, "unknown-job-0001", spec())
        self.jobs.ledger.begin(self.a, job["id"])
        self.jobs.close()
        self.jobs = JobService(ROOT, directory=self.directory, registry=self.registry)
        preview = self.jobs.preflight(self.a, spec())
        self.assertIn("job_admission_paused", preview["blockers"])
        self.assertFalse(preview["admitted_now"])
        self.assertFalse(self.jobs.run_one())
        self.assertEqual(self.jobs.ledger.balance(self.a)["spent_cents"], 0)


if __name__ == "__main__":
    unittest.main()
