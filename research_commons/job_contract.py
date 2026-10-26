"""Versioned, configuration-only contract for the local synthetic job slice."""
from market_lab.contract import validate_submission
from market_lab.data import manifest
from market_lab.io import LabError, canonical_bytes, digest, object_hash, read_bytes, source_hash

SKU = "synthetic_strategy_job.v1"
LIMITS = {"cpu_seconds": 2, "wall_seconds": 10, "memory_mib": 256,
          "output_bytes": 524288, "gpu": 0}
MAX_STATE_BYTES = 64 * 1024 * 1024
MIN_FREE_BYTES = 64 * 1024 * 1024
MAX_GLOBAL_ACTIVE = 8


def validate_job(root, params):
    if type(params) is not dict or set(params) != {
        "submission", "split", "resources", "max_price_cents"
    }:
        raise LabError("job requires only submission, split, resources and max_price_cents")
    if len(canonical_bytes(params)) > 32768 or params["split"] != "development":
        raise LabError("only bounded synthetic development jobs are admitted")
    if type(params["max_price_cents"]) is not int or not 50 <= params["max_price_cents"] <= 200:
        raise LabError("job must authorize the existing 50 simulated-cent price")
    resources = params["resources"]
    if type(resources) is not dict or set(resources) != set(LIMITS):
        raise LabError("exact resource contract required")
    for key, maximum in LIMITS.items():
        minimum = {"memory_mib": 128, "output_bytes": 16384, "gpu": 0}.get(key, 1)
        if type(resources[key]) is not int or not minimum <= resources[key] <= maximum:
            raise LabError("resource ceiling exceeded")
    validate_submission(root, params["submission"])
    return params


def job_source_hash(root):
    entries = {"engine": source_hash(root)}
    for name in ("__init__", "ledger", "job_contract", "job_queue", "job_worker", "job_limits", "job_http",
                 "sandbox_identity", "job_events", "job_handoff"):
        entries[name] = digest(read_bytes(root / "research_commons" / (name + ".py"), 256000))
    entries["schema"] = digest(read_bytes(root / "schemas" / "job.schema.json", 256000))
    return object_hash(entries)


def catalog(root):
    meta = manifest(root)
    return {"strategy": "liquidity_guard_v1", "sku": SKU,
            "dataset_id": meta["dataset_id"], "split": "development",
            "dataset_sha256": meta["splits"]["development"]["sha256"],
            "resources": LIMITS, "price_cents": 50,
            "evidence_level": "synthetic_engineering_only"}
