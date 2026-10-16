"""Public fixture metadata only; no external catalog or holdout evaluation."""

from market_lab.fixtures import expected_manifest


def datasets():
    manifest = expected_manifest()
    fields = [
        {"name": "timestamp", "type": "string", "unit": "UTC bar close", "nullable": False}
    ]
    for name in ("open", "high", "low", "close", "volume", "spread_bps",
                 "depth_usd", "open_interest_usd", "liquidation_usd"):
        unit = "invented quote USD / unit" if name in ("open", "high", "low", "close") else {
            "volume": "invented base units", "spread_bps": "basis points",
            "depth_usd": "invented USD", "open_interest_usd": "invented USD",
            "liquidation_usd": "invented USD",
        }[name]
        fields.append({"name": name, "type": "number", "unit": unit,
                       "nullable": name in ("spread_bps", "depth_usd", "open_interest_usd", "liquidation_usd")})
    return [{
        "id": manifest["dataset_id"], "title": "Liquidity deterioration lab",
        "synthetic": True, "asset": "TOY-USD", "venue": "NONE",
        "description": "Scripted early warnings, false alarms, unwarned shocks, and late warnings.",
        "granularity": "1h", "freshness": "Frozen fixture · no live updates",
        "retention": "Immutable v1 files retained in versioned source",
        "provenance": manifest["generator"],
        "license": "Apache-2.0 · original synthetic fixtures only",
        "coverage": [{"split": name, "start": item["first_close"], "end": item["last_close"],
                      "rows": item["rows"], "sha256": item["sha256"]}
                     for name, item in manifest["splits"].items()],
        "gaps": "24 omitted hours between splits. Depth missing at indices 17 and 133 in each split; unknown, not zero.",
        "fields": fields,
    }]
