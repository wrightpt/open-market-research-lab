"""Run from the checkout: python3 -m market_lab --help."""

import argparse
import json
import sys

from .contract import load_submission
from .data import load_split, manifest
from .io import ROOT, LabError, object_hash
from .research import development, freeze, holdout


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Local synthetic research mechanics; no market claims."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "verify-data", help="verify fixture hashes and structure; no outcome evaluation"
    )
    validate = commands.add_parser("validate", help="validate a bounded JSON submission")
    validate.add_argument("submission")
    backtest = commands.add_parser("backtest", help="run development only")
    backtest.add_argument("submission")
    backtest.add_argument("--output", default="artifacts/development.json")
    frozen = commands.add_parser(
        "freeze", help="bind a submission to development evidence and source"
    )
    frozen.add_argument("submission")
    frozen.add_argument("--development", required=True)
    frozen.add_argument("--output", default="artifacts/freeze.json")
    held = commands.add_parser("holdout", help="consume one holdout attempt using a freeze receipt")
    held.add_argument("receipt")
    held.add_argument("--output", default="artifacts/holdout.json")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify-data":
            metadata = manifest(ROOT)
            rows = {split: len(load_split(ROOT, split, metadata)) for split in metadata["splits"]}
            result = {"status": "verified", "dataset_id": metadata["dataset_id"], "rows": rows}
        elif args.command == "validate":
            submission = load_submission(ROOT, args.submission)
            result = {"status": "valid", "submission_sha256": object_hash(submission)}
        elif args.command == "freeze":
            receipt = freeze(ROOT, args.submission, args.development, args.output)
            result = {
                "status": "frozen", "output": args.output,
                "receipt_sha256": receipt["receipt_sha256"],
            }
        else:
            report = (
                development(ROOT, args.submission, args.output) if args.command == "backtest"
                else holdout(ROOT, args.receipt, args.output)
            )
            result = {
                "status": "complete", "output": args.output,
                "evidence_level": report["evidence_level"],
                "split": report["provenance"]["split"], "summary": report["summary"],
            }
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except LabError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError:
        print("error: local file operation failed; check paths and permissions", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
