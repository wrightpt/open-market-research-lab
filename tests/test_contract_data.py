import copy
import unittest

from helpers import RepoTest, baseline
from market_lab.contract import validate_schema, validate_submission
from market_lab.data import load_split, manifest, parse_bars
from market_lab.fixtures import DATA_DIR, expected_manifest, generate_split
from market_lab.io import ROOT, LabError, canonical_bytes, load_json, repo_path, write_new


class ContractTests(unittest.TestCase):
    def test_example_is_valid(self):
        self.assertEqual(validate_submission(ROOT, baseline()), baseline())

    def test_rejects_invalid_submissions(self):
        paths = [
            (("schema_version",), True),
            (("strategy", "name"), "import_anything"),
            (("strategy", "parameters", "lookback_bars"), True),
            (("strategy", "parameters", "lookback_bars"), 49),
            (("strategy", "parameters", "lookback_bars"), 3.5),
            (("strategy", "parameters", "min_signals"), 0),
            (("execution", "fee_bps"), -1),
            (("execution", "slippage_bps"), 101),
            (("execution", "initial_cash"), float("nan")),
            (("execution", "initial_cash"), float("inf")),
            (("execution", "initial_cash"), 10**1000),
            (("evaluation", "horizon_bars"), 25),
            (("dataset", "id"), "real-market"),
            (("dataset", "development_sha256"), "0" * 64),
            (("dataset", "holdout_sha256"), "0" * 64),
            (("budget", "parameter_sets"), 2),
            (("research", "evidence_level"), "predictive"),
            (("hypothesis",), "too short"),
            (("submission_id",), "x" * 65),
            (("execution", "position"), "short"),
        ]
        for path, value in paths:
            with self.subTest(path=path, value=str(value)[:40]):
                submission = copy.deepcopy(baseline())
                destination = submission
                for key in path[:-1]:
                    destination = destination[key]
                destination[path[-1]] = value
                with self.assertRaises(LabError):
                    validate_submission(ROOT, submission)

    def test_unknown_and_missing_fields_fail(self):
        submission = baseline()
        submission["strategy"]["code"] = "print('do not execute')"
        with self.assertRaisesRegex(LabError, "unknown field"):
            validate_submission(ROOT, submission)
        submission = baseline()
        del submission["execution"]["fee_bps"]
        with self.assertRaisesRegex(LabError, "required field"):
            validate_submission(ROOT, submission)

    def test_unknown_schema_keywords_fail_closed(self):
        with self.assertRaisesRegex(LabError, "unsupported schema"):
            validate_schema("x", {"type": "string", "format": "uri"})


class InputTests(RepoTest):
    def test_ambiguous_unbounded_or_nonfinite_json_fails(self):
        cases = [
            b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1e400}',
            b'{"a":' + b"9" * 5000 + b"}", b"[" * 18 + b"0" + b"]" * 18,
            b" " * 32769, b"\xff", b"{",
        ]
        for payload in cases:
            with self.subTest(payload=payload[:25]):
                path = self.root / "bad.json"
                path.write_bytes(payload)
                with self.assertRaises(LabError):
                    load_json(path)

    def test_output_and_input_path_boundaries(self):
        for name in ("../escape.json", "/escape.json", "artifacts/../../escape.json"):
            with self.assertRaises(LabError):
                repo_path(self.root, name)
        with self.assertRaises(LabError):
            write_new(self.root, "submissions/output.json", {})
        (self.root / "linked").symlink_to(self.root / "data", target_is_directory=True)
        with self.assertRaisesRegex(LabError, "symlink"):
            repo_path(self.root, "linked/synthetic-v1/development.csv")
        (self.root / "artifacts").symlink_to(self.root / "data", target_is_directory=True)
        with self.assertRaisesRegex(LabError, "symlink"):
            write_new(self.root, "artifacts/report.json", {})

    def test_evidence_is_exclusive(self):
        write_new(self.root, "artifacts/report.json", {"value": 1})
        with self.assertRaisesRegex(LabError, "already exists"):
            write_new(self.root, "artifacts/report.json", {"value": 2})
        self.assertEqual(load_json(self.root / "artifacts/report.json"), {"value": 1})


class DataTests(RepoTest):
    def test_exact_generation_identity_and_temporal_split(self):
        metadata = manifest(self.root)
        self.assertEqual(metadata, expected_manifest())
        for split, identity in metadata["splits"].items():
            with self.subTest(split=split):
                self.assertEqual((self.root / identity["file"]).read_bytes(), generate_split(split))
                bars = load_split(self.root, split)
                self.assertEqual(len(bars), identity["rows"])
        self.assertLess(metadata["splits"]["development"]["last_close"], metadata["splits"]["holdout"]["first_close"])

    def test_changed_fixture_and_manifest_rejected(self):
        path = self.root / DATA_DIR / "development.csv"
        path.write_bytes(path.read_bytes().replace(b"100.", b"101.", 1))
        with self.assertRaisesRegex(LabError, "SHA-256 mismatch"):
            load_split(self.root, "development")
        metadata = expected_manifest()
        metadata["synthetic"] = 1
        (self.root / DATA_DIR / "manifest.json").write_bytes(canonical_bytes(metadata))
        with self.assertRaisesRegex(LabError, "manifest differs"):
            manifest(self.root)

    def test_missing_market_features_are_unknown(self):
        bars = load_split(self.root, "development")
        self.assertIsNone(bars[17].depth_usd)
        self.assertIsNotNone(bars[16].depth_usd)

    def test_invalid_csv_is_rejected(self):
        lines = generate_split("development").decode().splitlines()
        header, first, second = lines[:3]
        base = first.split(",")
        variants = [
            (0, "2024-01-01T03:00:00Z"), (1, "nan"), (2, "0.01"),
            (3, "9999"), (4, ""), (5, "-1"), (6, "inf"), (7, "0"), (8, "-2"),
        ]
        for field, value in variants:
            with self.subTest(field=field, value=value):
                changed = base[:]
                changed[field] = value
                payload = ("\n".join([header, ",".join(changed), second]) + "\n").encode()
                with self.assertRaises(LabError):
                    parse_bars(payload)
        for payload in (
            f"{header}\n{first}\n{first}\n", f"{header}\n{first},extra\n{second}\n",
            f"wrong\n{first}\n{second}\n", f"{header}\n{first}\n",
        ):
            with self.assertRaises(LabError):
                parse_bars(payload.encode())

    def test_csv_resource_limit(self):
        with self.assertRaisesRegex(LabError, "exceeds"):
            parse_bars(b" " * 256001)


if __name__ == "__main__":
    unittest.main()
