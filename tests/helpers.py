"""Test workspaces live inside this checkout; no external files or services."""

import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from market_lab.data import parse_bars
from market_lab.fixtures import generate_split
from market_lab.io import ROOT, load_json


def flat_bars(count=8, price=100):
    rows = parse_bars(generate_split("development"))[:count]
    return [replace(
        row, open=price, high=price, low=price, close=price, volume=1000,
        spread_bps=10, depth_usd=1000, open_interest_usd=10000, liquidation_usd=0,
    ) for row in rows]


def baseline():
    return load_json(ROOT / "submissions/baseline.json")


class RepoTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "artifacts").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="test-", dir=ROOT / "artifacts")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in ("market_lab", "schemas", "submissions", "data"):
            shutil.copytree(ROOT / name, self.root / name, ignore=shutil.ignore_patterns("__pycache__"))
