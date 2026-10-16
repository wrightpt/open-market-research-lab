import contextlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from helpers import RepoTest
from market_lab.__main__ import main
from market_lab.io import LabError, canonical_bytes, load_json
from market_lab.research import CONSUMED, development, freeze, holdout


class ResearchTests(RepoTest):
    def prepare(self):
        report = development(self.root, "submissions/baseline.json", "artifacts/dev.json")
        receipt = freeze(self.root, "submissions/baseline.json", "artifacts/dev.json", "artifacts/freeze.json")
        return report, receipt

    def test_development_is_reproducible_without_loading_holdout(self):
        from market_lab.research import load_split
        with patch("market_lab.research.load_split", wraps=load_split) as loader:
            first = development(self.root, "submissions/baseline.json", "artifacts/a.json")
            second = development(self.root, "submissions/baseline.json", "artifacts/b.json")
        self.assertEqual(first, second)
        self.assertTrue(all(call.args[1] == "development" for call in loader.call_args_list))
        self.assertEqual((self.root / "artifacts/a.json").read_bytes(), (self.root / "artifacts/b.json").read_bytes())
        self.assertFalse((self.root / CONSUMED).exists())
        self.assertEqual(first["controls"]["always_cash"]["final_equity"], 10000)
        self.assertEqual(first["evidence_level"], "synthetic_engineering_only")
        for fill in first["fills"]:
            if fill["timing"] == "next_open":
                self.assertEqual(fill["bar"], fill["decision_bar"] + 1)

    def test_holdout_gate_one_attempt_without_scoring_checked_in_holdout(self):
        _, receipt = self.prepare()
        # Gate test only: no feature, backtest, or outcome calculation on holdout.
        with patch("market_lab.research.build_report", return_value={"gate_test_only": True}) as build:
            result = holdout(self.root, "artifacts/freeze.json", "artifacts/holdout.json")
            self.assertEqual(result["freeze_sha256"], receipt["receipt_sha256"])
            self.assertEqual(build.call_count, 1)
            self.assertTrue((self.root / CONSUMED).exists())
            with self.assertRaisesRegex(LabError, "already exists"):
                holdout(self.root, "artifacts/freeze.json", "artifacts/holdout-again.json")
            self.assertEqual(build.call_count, 1)
        with self.assertRaisesRegex(LabError, "already been consumed"):
            freeze(self.root, "submissions/baseline.json", "artifacts/dev.json", "artifacts/refreeze.json")

    def test_concurrent_attempts_admit_only_one(self):
        self.prepare()
        def attempt(index):
            try:
                holdout(self.root, "artifacts/freeze.json", f"artifacts/held-{index}.json")
                return True
            except LabError:
                return False
        with patch("market_lab.research.build_report", side_effect=lambda *args: {"gate_test_only": True}):
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(sorted(pool.map(attempt, (1, 2))), [False, True])

    def test_source_drift_prevents_holdout_before_consumption(self):
        self.prepare()
        path = self.root / "market_lab/strategy.py"
        path.write_bytes(path.read_bytes() + b"\n# changed after freeze\n")
        with self.assertRaisesRegex(LabError, "changed after freeze"):
            holdout(self.root, "artifacts/freeze.json", "artifacts/held.json")
        self.assertFalse((self.root / CONSUMED).exists())

    def test_development_evidence_drift_prevents_holdout(self):
        self.prepare()
        path = self.root / "artifacts/dev.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(LabError, "evidence changed"):
            holdout(self.root, "artifacts/freeze.json", "artifacts/held.json")
        self.assertFalse((self.root / CONSUMED).exists())

    def test_failed_holdout_remains_consumed(self):
        self.prepare()
        path = self.root / "data/synthetic-v1/holdout.csv"
        path.write_bytes(b"broken fixture")
        with self.assertRaisesRegex(LabError, "SHA-256 mismatch"):
            holdout(self.root, "artifacts/freeze.json", "artifacts/held.json")
        self.assertTrue((self.root / CONSUMED).exists())
        with self.assertRaisesRegex(LabError, "already exists"):
            holdout(self.root, "artifacts/freeze.json", "artifacts/held-2.json")

    def test_freeze_rejects_changed_submission(self):
        development(self.root, "submissions/baseline.json", "artifacts/dev.json")
        path = self.root / "submissions/baseline.json"
        submission = load_json(path)
        submission["execution"]["fee_bps"] = 6
        path.write_bytes(canonical_bytes(submission))
        with self.assertRaisesRegex(LabError, "development evidence must match"):
            freeze(self.root, "submissions/baseline.json", "artifacts/dev.json", "artifacts/frozen.json")

    def test_tampered_receipt_rejected(self):
        self.prepare()
        path = self.root / "artifacts/freeze.json"
        receipt = load_json(path)
        receipt["submission"]["execution"]["fee_bps"] = 6
        path.write_bytes(canonical_bytes(receipt))
        with self.assertRaisesRegex(LabError, "freeze receipt identity"):
            holdout(self.root, "artifacts/freeze.json", "artifacts/held.json")

    def test_existing_holdout_output_does_not_consume(self):
        self.prepare()
        (self.root / "artifacts/existing.json").write_text("preserve")
        with self.assertRaisesRegex(LabError, "output already exists"):
            holdout(self.root, "artifacts/freeze.json", "artifacts/existing.json")
        self.assertFalse((self.root / CONSUMED).exists())


class CliTests(RepoTest):
    def invoke(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("market_lab.__main__.ROOT", self.root):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_human_quickstart_and_freeze(self):
        for command in (
            ["verify-data"], ["validate", "submissions/baseline.json"],
            ["backtest", "submissions/baseline.json"],
            ["freeze", "submissions/baseline.json", "--development", "artifacts/development.json"],
        ):
            with self.subTest(command=command):
                code, stdout, stderr = self.invoke(command)
                self.assertEqual((code, stderr), (0, ""))
                self.assertIn("status", json.loads(stdout))
        self.assertFalse((self.root / CONSUMED).exists())

    def test_cli_errors_are_nonzero_without_tracebacks_or_hostpaths(self):
        for command in (
            ["validate", "missing.json"], ["validate", "../outside.json"],
            ["backtest", "submissions/baseline.json", "--output", "README.md"],
        ):
            code, stdout, stderr = self.invoke(command)
            self.assertEqual((code, stdout), (2, ""))
            self.assertTrue(stderr.startswith("error: "))
            self.assertNotIn("Traceback", stderr)
            self.assertNotIn(str(self.root), stderr)

    def test_backtest_has_no_holdout_switch(self):
        with self.assertRaises(SystemExit) as raised:
            self.invoke(["backtest", "submissions/baseline.json", "--split", "holdout"])
        self.assertEqual(raised.exception.code, 2)
