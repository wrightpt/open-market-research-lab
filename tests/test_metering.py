"""Offline metering regression and adversarial fixtures; no live payment or network."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import TestCase, main, mock
import sqlite3
import tempfile

from market_lab.io import ROOT, LabError, object_hash
from research_commons.ledger import (
    MAX_OPERATIONS, FixturePrincipal, FixtureRegistry, MeterError, OfflineLedger,
)
from research_commons.meter_service import OfflineResearchService

DATA = {"offset": 0, "limit": 2}


class OfflineMeteringTests(TestCase):
    def setUp(self):
        (ROOT / "artifacts").mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix="metering-test-", dir=ROOT / "artifacts")
        self.directory = f"artifacts/{Path(self.tmp.name).name}/ledger"
        self.now = 1000.0
        self.registry = FixtureRegistry({"test-alpha": 100, "test-beta": 100})
        self.alpha = self.registry.issue("test-alpha")
        self.beta = self.registry.issue("test-beta")
        self.ledger = OfflineLedger(
            ROOT, self.registry, directory=self.directory, clock=lambda: self.now)
        self.service = OfflineResearchService(self.ledger)

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_two_real_synthetic_skus_and_holdout_never_evaluated(self):
        q = self.service.quote(self.alpha, "synthetic_sample.v1", DATA)
        self.assertEqual(q["price_cents"], 2)
        self.assertEqual(q["mode"], "offline_fixture_no_real_funds")
        original_load = __import__("research_commons.meter_service", fromlist=["load_split"]).load_split
        with mock.patch("research_commons.meter_service.load_split",
                        wraps=original_load) as loader:
            one = self.service.purchase_fixture(self.alpha, "data-read-001", "synthetic_sample.v1", DATA)
            self.assertEqual(loader.call_args.args[1], "development")
        self.assertEqual(one["state"], "settled")
        self.assertEqual(one["charged_cents"], 2)
        self.assertEqual(len(one["result"]["rows"]), 2)
        self.assertEqual(one["result"]["evidence_level"], "synthetic_engineering_only")
        two = self.service.purchase_fixture(self.alpha, "fixed-run-001", "synthetic_backtest.v1", {})
        self.assertEqual(two["state"], "settled")
        self.assertEqual(two["charged_cents"], 50)
        self.assertEqual(len(two["result"]["study_id"]), 16)
        self.assertEqual(len(two["evidence_sha256"]), 64)
        self.assertEqual(two["result"]["split"], "development")
        self.assertTrue(two["result"]["replay_matched"])
        self.assertEqual(two["result"]["report_sha256"], two["result"]["replay_sha256"])
        self.assertEqual(self.ledger.balance(self.alpha)["available_cents"], 48)
        self.assertEqual(len(self.ledger.events(self.alpha, two["id"])), 3)
        self.assertTrue(self.ledger.verify_audit())

    def test_simultaneous_purchase_claims_one_execution(self):
        original = self.service._dispatch

        def slow_dispatch(*args):
            import time
            time.sleep(0.03)
            return original(*args)

        with mock.patch.object(self.service, "_dispatch", side_effect=slow_dispatch) as dispatcher:
            def buy(_):
                return self.service.purchase_fixture(
                    self.alpha, "simultaneous-purchase-001", "synthetic_sample.v1", DATA)

            with ThreadPoolExecutor(max_workers=2) as pool:
                receipts = list(pool.map(buy, range(2)))
            self.assertEqual(dispatcher.call_count, 1)
        self.assertEqual(len({r["id"] for r in receipts}), 1)
        self.assertEqual(self.ledger.get(self.alpha, receipts[0]["id"])["state"], "settled")
        self.assertEqual(self.ledger.balance(self.alpha)["spent_cents"], 2)

    def test_replay_never_runs_twice(self):
        with mock.patch.object(self.service, "_dispatch", wraps=self.service._dispatch) as dispatch:
            first = self.service.purchase_fixture(self.alpha, "replay-key-001",
                                                  "synthetic_sample.v1", DATA)
            second = self.service.purchase_fixture(self.alpha, "replay-key-001",
                                                   "synthetic_sample.v1", DATA)
            self.assertEqual(first, second)
            self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(self.ledger.balance(self.alpha)["spent_cents"], 2)

    def test_idempotency_key_body_and_sku_are_bound(self):
        first = self.ledger.reserve(self.alpha, "original-key-001", "synthetic_sample.v1", DATA)
        self.assertEqual(first, self.ledger.reserve(self.alpha, "original-key-001",
                                                    "synthetic_sample.v1", DATA))
        with self.assertRaisesRegex(MeterError, "different request"):
            self.ledger.reserve(self.alpha, "original-key-001",
                                "synthetic_sample.v1", {"offset": 0, "limit": 3})
        with self.assertRaisesRegex(MeterError, "different request"):
            self.ledger.reserve(self.alpha, "original-key-001",
                                "synthetic_backtest.v1", {})
        self.assertEqual(self.ledger.balance(self.alpha)["operations"], 1)

    def test_untrusted_subject_and_cross_tenant_receipt_denied(self):
        receipt = self.ledger.reserve(self.alpha, "tenant-guard-001", "synthetic_sample.v1", DATA)
        with self.assertRaisesRegex(MeterError, "unavailable"):
            self.ledger.get(self.beta, receipt["id"])
        with self.assertRaisesRegex(MeterError, "unavailable"):
            self.ledger.events(self.beta, receipt["id"])
        with self.assertRaisesRegex(MeterError, "principal required"):
            self.ledger.balance(FixturePrincipal("test-alpha", "fake-token"))
        with self.assertRaisesRegex(MeterError, "principal required"):
            self.ledger.quote("test-alpha", "synthetic_sample.v1", DATA)
        self.assertEqual(self.ledger.balance(self.beta)["available_cents"], 100)

    def test_concurrent_same_key_reserves_only_once(self):
        def reserve(_):
            return self.ledger.reserve(
                self.alpha, "same-concurrent-key", "synthetic_sample.v1", DATA)["id"]
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(reserve, range(12)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(self.ledger.balance(self.alpha)["held_cents"], 2)
        self.assertEqual(self.ledger.balance(self.alpha)["operations"], 1)

    def test_concurrent_distinct_keys_respect_budget_and_inflight(self):
        def reserve(i):
            try:
                return self.ledger.reserve(
                    self.alpha, f"many-reservations-{i:02d}",
                    "synthetic_backtest.v1", {})["id"]
            except MeterError:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(reserve, range(12)))
        self.assertEqual(len([x for x in results if x]), 2)
        self.assertEqual(self.ledger.balance(self.alpha)["available_cents"], 0)
        self.assertEqual(self.ledger.balance(self.alpha)["held_cents"], 100)

    def test_exclusive_claim_prevents_double_execution(self):
        receipt = self.ledger.reserve(self.alpha, "claimed-only-key", "synthetic_sample.v1", DATA)
        a, claimed_a = self.ledger.begin(self.alpha, receipt["id"])
        b, claimed_b = self.ledger.begin(self.alpha, receipt["id"])
        self.assertTrue(claimed_a)
        self.assertFalse(claimed_b)
        self.assertEqual(a["state"], b["state"])
        self.assertEqual(a["state"], "executing")
        self.ledger.finish(self.alpha, receipt["id"], "failed", reason="execution_failed")
        self.assertEqual(self.ledger.balance(self.alpha)["held_cents"], 0)

    def test_stale_executing_claim_becomes_uncertain_and_never_replayed(self):
        receipt = self.ledger.reserve(self.alpha, "crashed-claim-key", "synthetic_sample.v1", DATA)
        claimed, did_claim = self.ledger.begin(self.alpha, receipt["id"])
        self.assertTrue(did_claim)
        self.assertEqual(claimed["state"], "executing")
        self.ledger.close()
        self.ledger = OfflineLedger(
            ROOT, self.registry, directory=self.directory, clock=lambda: self.now)
        self.service = OfflineResearchService(self.ledger)
        recovered = self.ledger.get(self.alpha, receipt["id"])
        self.assertEqual(recovered["state"], "uncertain")
        self.assertEqual(recovered["charged_cents"], 0)
        self.assertEqual(self.ledger.balance(self.alpha)["available_cents"], 100)
        duplicate = self.service.purchase_fixture(
            self.alpha, "crashed-claim-key", "synthetic_sample.v1", DATA)
        self.assertEqual(duplicate["state"], "uncertain")
        self.assertEqual(len(self.ledger.events(self.alpha, receipt["id"])), 3)

    def test_expiry_and_manual_cancel_release_reservations(self):
        a = self.ledger.reserve(self.alpha, "ttl-expire-001", "synthetic_backtest.v1", {})
        self.now += 61
        self.ledger.expire()
        self.assertEqual(self.ledger.get(self.alpha, a["id"])["state"], "expired")
        self.assertEqual(self.ledger.balance(self.alpha)["available_cents"], 100)
        b = self.ledger.reserve(self.alpha, "cancel-request-001", "synthetic_sample.v1", DATA)
        cancelled = self.ledger.finish(self.alpha, b["id"], "cancelled", reason="client_cancelled")
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertEqual(cancelled["charged_cents"], 0)
        self.assertEqual(self.ledger.balance(self.alpha)["held_cents"], 0)

    def test_refund_restores_credits_and_keeps_original_receipt(self):
        receipt = self.service.purchase_fixture(
            self.alpha, "refundable-001", "synthetic_sample.v1", DATA)
        self.assertEqual(self.ledger.balance(self.alpha)["spent_cents"], 2)
        refunded = self.ledger.finish(self.alpha, receipt["id"], "refunded", reason="fixture_refund")
        self.assertEqual(refunded["state"], "refunded")
        self.assertEqual(refunded["charged_cents"], 0)
        self.assertEqual(refunded["result"], receipt["result"])
        self.assertEqual(self.ledger.balance(self.alpha)["available_cents"], 100)
        with self.assertRaisesRegex(MeterError, "invalid ledger transition"):
            self.ledger.finish(self.alpha, receipt["id"], "settled",
                               result=receipt["result"], digest=receipt["evidence_sha256"])

    def test_failure_releases_budget_and_preserves_evidence_state(self):
        with mock.patch.object(self.service, "_dispatch", side_effect=LabError("bad fixture")):
            failed = self.service.purchase_fixture(
                self.alpha, "bad-source-001", "synthetic_backtest.v1", {})
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["failure"], "execution_failed")
        self.assertIsNone(failed["result"])
        self.assertEqual(self.ledger.balance(self.alpha)["available_cents"], 100)
        self.assertEqual(self.service.purchase_fixture(
            self.alpha, "bad-source-001", "synthetic_backtest.v1", {})["state"], "failed")

    def test_source_drift_cancels_before_execution(self):
        prior = self.ledger.reserve(self.alpha, "source-drift-001", "synthetic_sample.v1", DATA)
        with mock.patch.object(self.ledger, "_identity", return_value=("0" * 64, "1" * 64)):
            cancelled, acquired = self.ledger.begin(self.alpha, prior["id"])
        self.assertFalse(acquired)
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertEqual(cancelled["failure"], "source_drift")
        self.assertEqual(self.ledger.balance(self.alpha)["available_cents"], 100)

    def test_private_source_and_unbounded_calls_fail_closed(self):
        illegal = [
            ("holdout.v1", {}), ("synthetic_backtest.v1", {"code": "print(1)"}),
            ("synthetic_sample.v1", {"offset": 0, "limit": 21}),
            ("synthetic_sample.v1", {"offset": True, "limit": 2}),
            ("synthetic_sample.v1", {"offset": 383, "limit": 2}),
            ("synthetic_sample.v1", {"offset": 0, "limit": 1, "split": "holdout"}),
        ]
        for sku, params in illegal:
            with self.subTest(sku=sku, params=params), self.assertRaises(MeterError):
                self.service.quote(self.alpha, sku, params)
        with mock.patch("research_commons.ledger.manifest", return_value={
            "dataset_id": "live-private", "synthetic": False
        }):
            with self.assertRaises(MeterError):
                self.service.quote(self.alpha, "synthetic_sample.v1", DATA)

    def test_large_result_fails_without_billing(self):
        with mock.patch.object(self.service, "_dispatch",
                               return_value=({"rows": ["x" * 40_000]}, "a" * 64)):
            failed = self.service.purchase_fixture(
                self.alpha, "too-large-result", "synthetic_sample.v1", DATA)
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(self.ledger.balance(self.alpha)["spent_cents"], 0)

    def test_operation_quota_counts_failures_too(self):
        self.ledger.close()
        self.registry = FixtureRegistry({"test-alpha": 10_000})
        self.alpha = self.registry.issue("test-alpha")
        self.ledger = OfflineLedger(
            ROOT, self.registry,
            directory=f"artifacts/{Path(self.tmp.name).name}/quota")
        for i in range(MAX_OPERATIONS):
            r = self.ledger.reserve(
                self.alpha, f"quota-operation-{i:03d}", "synthetic_sample.v1", DATA)
            self.ledger.finish(self.alpha, r["id"], "cancelled", reason="fixture_cancel")
        with self.assertRaisesRegex(MeterError, "quota exhausted"):
            self.ledger.reserve(self.alpha, "quota-operation-overflow", "synthetic_sample.v1", DATA)

    def test_tamper_is_detected_and_events_cannot_be_edited(self):
        self.ledger.reserve(self.alpha, "audit-tamper-001", "synthetic_sample.v1", DATA)
        db = sqlite3.connect(self.ledger.db_path)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("UPDATE events SET event_hash=? WHERE seq=1", ("x",))
            # Simulate privileged local filesystem/DB tampering, not user input.
            db.execute("DROP TRIGGER no_event_update")
            db.execute("UPDATE events SET event_hash=? WHERE seq=1", ("0" * 64,))
            db.commit()
        finally:
            db.close()
        with self.assertRaisesRegex(MeterError, "audit digest mismatch"):
            self.ledger.verify_audit()

    def test_modified_receipt_price_fails_projection_audit(self):
        receipt = self.ledger.reserve(
            self.alpha, "tampered-price-001", "synthetic_sample.v1", DATA)
        db = sqlite3.connect(self.ledger.db_path)
        try:
            db.execute("UPDATE operations SET price_cents=99 WHERE id=?", (receipt["id"],))
            db.commit()
        finally:
            db.close()
        with self.assertRaisesRegex(MeterError, "receipt differs from audit"):
            self.ledger.verify_audit()


if __name__ == "__main__":
    main()
