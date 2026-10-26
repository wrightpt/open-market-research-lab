"""Fixed subprocess entrypoint. No CLI, plugin, path or command from submissions."""
import json
import resource
import sys

from market_lab.data import load_split, manifest
from market_lab.io import ROOT, canonical_bytes, object_hash, _check_tree, _unique_pairs
from market_lab.research import build_report_from_inputs, provenance
from .job_contract import validate_job, job_source_hash
from .job_limits import install_limits


def main():
    request = json.loads(sys.stdin.buffer.read(40001), object_pairs_hook=_unique_pairs)
    _check_tree(request)
    spec = validate_job(ROOT, request["spec"])
    if job_source_hash(ROOT) != request["source_sha256"]:
        raise ValueError("source drift before worker initialization")
    metadata = manifest(ROOT)
    if object_hash(metadata) != request["manifest_sha256"]:
        raise ValueError("dataset drift before worker initialization")
    bars = load_split(ROOT, "development", metadata)
    frozen = provenance(ROOT, spec["submission"], metadata, "development")
    enforcement = install_limits(spec["resources"], request["parent_pid"])
    report = build_report_from_inputs(spec["submission"], bars, frozen)
    replay = build_report_from_inputs(spec["submission"], bars, frozen)
    sha = object_hash(report)
    if sha != object_hash(replay):
        raise ValueError("same-engine replay mismatch")
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {"report": report, "report_sha256": sha, "replay_sha256": sha,
              "enforcement": enforcement, "cpu_seconds": usage.ru_utime + usage.ru_stime,
              "max_rss_kib": usage.ru_maxrss}
    raw = canonical_bytes(result)
    if len(raw) > spec["resources"]["output_bytes"]:
        raise ValueError("worker output ceiling exceeded")
    sys.stdout.buffer.write(raw)


if __name__ == "__main__":
    main()
