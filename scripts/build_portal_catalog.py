"""Build the static, synthetic-only public catalog from checked-in source data.

This module must remain stdlib-only and has no database, network, or API access.
"""

import argparse
import csv
import io
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "synthetic-v1" / "manifest.json"
OUTPUT = ROOT / "portal" / "catalog.json"

# Source of truth for field meaning: DATA_POLICY.md.
FIELDS = {
    "timestamp": ("UTC date-time", "Bar-close time; all features available at close"),
    "open": ("synthetic quote", "Open of the preceding one-hour synthetic bar"),
    "high": ("synthetic quote", "High of the synthetic bar"),
    "low": ("synthetic quote", "Low of the synthetic bar"),
    "close": ("synthetic quote", "Close of the synthetic bar"),
    "volume": ("invented units", "Nonnegative synthetic volume"),
    "spread_bps": ("basis points", "Synthetic quoted spread"),
    "depth_usd": ("invented USD", "Synthetic near-mid aggregate depth, not an order book"),
    "open_interest_usd": ("invented USD", "Synthetic derivative open interest"),
    "liquidation_usd": ("invented USD", "Synthetic liquidation context"),
}


def build_catalog(root: Path = ROOT) -> dict:
    manifest = json.loads((root / "data/synthetic-v1/manifest.json").read_text())
    fixture = root / manifest["splits"]["development"]["file"]
    with fixture.open("r", encoding="utf-8", newline="") as fh:
        fields = next(csv.reader(fh))
    if set(fields) != set(FIELDS) or len(fields) != len(FIELDS):
        raise ValueError("Source fixture fields no longer match documented field definitions")
    if manifest.get("synthetic") is not True or manifest.get("venue") != "NONE":
        raise ValueError("Only generated synthetic fixtures may enter the portal catalog")

    splits = {}
    for name in ("development", "holdout"):
        part = manifest["splits"][name]
        splits[name] = {
            "rows": part["rows"],
            "first_close": part["first_close"],
            "last_close": part["last_close"],
            "sha256": part["sha256"],
            "source_path": part["file"],
            "visibility": "public_fixture",
            "use": "development_experiments" if name == "development" else "holdout_mechanics_only",
        }

    return {
        "schema_version": 1,
        "dataset_id": manifest["dataset_id"],
        "title": "Synthetic liquidity and deleveraging benchmark",
        "summary": (
            "A deterministic toy market panel for testing lookahead safety, "
            "transaction-cost accounting, and reproducibility. Not real market data."
        ),
        "source_kind": "synthetic_generated",
        "redistribution": "Apache-2.0 original synthetic fixtures",
        "access_method": "git_clone_local_files",
        "api_availability": "not_available",
        "mcp_availability": "not_available",
        "requires_key": False,
        "instrument": manifest["instrument"],
        "venue": manifest["venue"],
        "interval_seconds": manifest["interval_seconds"],
        "timestamp_semantics": manifest["timestamp_semantics"],
        "embargo_bars": manifest["embargo_bars"],
        "splits": splits,
        "fields": [
            {"name": name, "unit": FIELDS[name][0], "description": FIELDS[name][1]}
            for name in fields
        ],
        "source_manifest": "data/synthetic-v1/manifest.json",
        "caveats": [
            "Synthetic scenarios do not establish predictive performance or profitability.",
            "The holdout fixture is public and is not independently blinded market evidence.",
            "No private database, Kubernetes, Vault, exchange, or trading access is available.",
        ],
    }


def serialize(value: dict) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify or update the public synthetic catalog")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Compare committed catalog to source")
    group.add_argument("--write", action="store_true", help="Write catalog from committed fixtures")
    args = parser.parse_args(argv)
    expected = serialize(build_catalog())
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
            print("FAIL: portal/catalog.json differs from data/synthetic-v1/manifest.json")
            return 1
        print("PASS: synthetic public catalog matches the checked-in manifest")
        return 0
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    print("Updated portal/catalog.json from original synthetic fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
