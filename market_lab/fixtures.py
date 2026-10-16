"""Transparent synthetic generator, never a source of market evidence.

Integer arithmetic and an explicit LCG make the CSV bytes reproducible. The
scenario calendar belongs to construction only; it is never a strategy input.
"""

import csv
import io
from datetime import datetime, timedelta, timezone

from .io import digest

DATASET_ID = "synthetic-liquidity-v1"
DATA_DIR = "data/synthetic-v1"
FIELDS = (
    "timestamp", "open", "high", "low", "close", "volume",
    "spread_bps", "depth_usd", "open_interest_usd", "liquidation_usd",
)
SPLITS = {
    "development": (384, 20261015, 0, 0),
    "holdout": (192, 73421, 408, 1),
}
EPOCH = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _price(value):
    return f"{value // 1_000_000}.{value % 1_000_000:06d}"


def generate_split(split):
    count, state, offset, scenario_offset = SPLITS[split]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(FIELDS)
    previous = 100_000_000

    def noise(span):
        nonlocal state
        state = (1664525 * state + 1013904223) % 2**32
        return state % span

    for index in range(count):
        phase = index % 96
        scenario = (index // 96 + scenario_offset) % 4
        # Lead warning + crash, false alarm, unwarned crash, late warning.
        warning = (scenario in (0, 1) and 44 <= phase <= 58) or (
            scenario == 3 and 58 <= phase <= 72
        )
        shock = scenario != 1 and 56 <= phase <= 60
        opening = previous * (10_000 + noise(17) - 8) // 10_000
        movement = noise(31) - 12 - (160 if shock else 0)
        close = opening * (10_000 + movement) // 10_000
        high = max(opening, close) * (10_000 + 5 + noise(16)) // 10_000
        low = min(opening, close) * (10_000 - 5 - noise(16)) // 10_000
        spread = 7 + noise(5) + (18 if warning else 0)
        depth = 1_000_000 + noise(50_000) - (650_000 if warning else 0)
        oi = 10_000_000 + noise(100_000) - (1_500_000 if warning else 0)
        liquidation = noise(800) + (70_000 if shock else 0)
        timestamp = (EPOCH + timedelta(hours=offset + index + 1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        writer.writerow([
            timestamp, _price(opening), _price(high), _price(low), _price(close),
            1000 + noise(900) + (3000 if shock else 0), spread,
            "" if index in (17, 133) else depth, oi, liquidation,
        ])
        previous = close
    return stream.getvalue().encode("ascii")


def expected_manifest():
    splits = {}
    for name, (count, seed, offset, scenario) in SPLITS.items():
        splits[name] = {
            "file": f"{DATA_DIR}/{name}.csv",
            "sha256": digest(generate_split(name)),
            "rows": count,
            "seed": seed,
            "scenario_offset": scenario,
            "first_close": (EPOCH + timedelta(hours=offset + 1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "last_close": (EPOCH + timedelta(hours=offset + count)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
    return {
        "schema_version": 1,
        "dataset_id": DATASET_ID,
        "synthetic": True,
        "instrument": "SYNTHETIC:TOY-USD",
        "venue": "NONE",
        "generator": "market_lab.fixtures:v1:integer-lcg",
        "interval_seconds": 3600,
        "embargo_bars": 24,
        "timestamp_semantics": "bar close UTC; all fields available at close",
        "splits": splits,
    }
