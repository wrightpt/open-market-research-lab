"""Versioned fixture custody and bounded, fail-closed CSV parsing."""

import csv
import io
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .fixtures import DATA_DIR, FIELDS, expected_manifest
from .io import LabError, digest, load_json, object_hash, read_bytes, repo_path

MAX_ROWS = 1000


@dataclass(frozen=True)
class Bar:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    spread_bps: float | None
    depth_usd: float | None
    open_interest_usd: float | None
    liquidation_usd: float | None


def manifest(root):
    value = load_json(repo_path(root, f"{DATA_DIR}/manifest.json"))
    if object_hash(value) != object_hash(expected_manifest()):
        raise LabError("manifest differs from the versioned synthetic generator")
    return value


def parse_bars(payload):
    if len(payload) > 256_000:
        raise LabError("CSV exceeds 256000 bytes")
    try:
        reader = csv.DictReader(io.StringIO(payload.decode("ascii"), newline=""))
        if reader.fieldnames != list(FIELDS):
            raise LabError("unexpected CSV columns or order")
        bars = []
        previous_time = None
        for row in reader:
            if len(bars) >= MAX_ROWS:
                raise LabError("CSV exceeds 1000 bars")
            if None in row or any(v is None for v in row.values()):
                raise LabError("CSV row has the wrong number of fields")
            timestamp = datetime.strptime(row["timestamp"], "%Y-%m-%dT%H:%M:%SZ")
            if timestamp.strftime("%Y-%m-%dT%H:%M:%SZ") != row["timestamp"]:
                raise LabError("timestamps must be canonical UTC")
            if previous_time is not None and timestamp - previous_time != timedelta(hours=1):
                raise LabError("timestamps must be strictly increasing hourly bars")
            previous_time = timestamp
            values = {}
            for field in FIELDS[1:]:
                if row[field] == "" and field in FIELDS[6:]:
                    values[field] = None
                    continue
                number = float(row[field])
                positive = field in (
                    "open", "high", "low", "close", "depth_usd", "open_interest_usd"
                )
                minimum = 0.00000001 if positive else 0
                if not math.isfinite(number) or not minimum <= number <= 1e12:
                    raise LabError(f"invalid finite range for {field}")
                values[field] = number
            if not (
                values["low"] <= min(values["open"], values["close"])
                <= max(values["open"], values["close"]) <= values["high"]
            ):
                raise LabError("inconsistent OHLC bounds")
            bars.append(Bar(row["timestamp"], **values))
    except (UnicodeError, ValueError, csv.Error) as exc:
        if isinstance(exc, LabError):
            raise
        raise LabError("malformed CSV value") from exc
    if len(bars) < 2:
        raise LabError("at least two bars are required")
    return bars


def load_split(root, split, metadata=None):
    if split not in ("development", "holdout"):
        raise LabError("unknown split")
    metadata = manifest(root) if metadata is None else metadata
    identity = metadata["splits"][split]
    payload = read_bytes(repo_path(root, identity["file"]), 256_000)
    if digest(payload) != identity["sha256"]:
        raise LabError(f"{split} fixture SHA-256 mismatch")
    bars = parse_bars(payload)
    if (len(bars), bars[0].timestamp, bars[-1].timestamp) != (
        identity["rows"], identity["first_close"], identity["last_close"]
    ):
        raise LabError("fixture row count or time bounds mismatch")
    return bars
