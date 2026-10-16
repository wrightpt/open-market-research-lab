"""Reports, freeze receipts, and a local one-attempt holdout guard."""

from . import __version__
from .contract import load_submission, validate_submission
from .data import load_split, manifest
from .engine import simulate
from .evaluation import evaluate_alerts
from .fixtures import DATASET_ID
from .io import (
    LabError, digest, load_json, object_hash, read_bytes, repo_path, source_hash, write_new,
)
from .strategy import causal_features, decide

EVIDENCE = "synthetic_engineering_only"
CONSUMED = f"artifacts/{DATASET_ID}.holdout-consumed.json"
MAX_REPORT_BYTES = 2_000_000


def provenance(root, submission, metadata, split):
    return {
        "engine_version": __version__, "source_sha256": source_hash(root),
        "submission_sha256": object_hash(submission),
        "manifest_sha256": object_hash(metadata),
        "dataset_id": metadata["dataset_id"], "instrument": metadata["instrument"],
        "split": split, "dataset_sha256": metadata["splits"][split]["sha256"],
    }


def build_report(root, submission, metadata, split, bars):
    parameters = submission["strategy"]["parameters"]
    lookback = parameters["lookback_bars"]
    features = causal_features(bars, lookback)
    decisions = decide(features, parameters)
    simulation = simulate(bars, [d["target"] for d in decisions], submission["execution"])
    controls = {}
    for name, active in (("always_cash", False), ("always_long_after_warmup", True)):
        targets = [int(active and i >= lookback) for i in range(len(bars))]
        controls[name] = simulate(bars, targets, submission["execution"])["summary"]
    return {
        "schema_version": 1, "evidence_level": EVIDENCE,
        "interpretation": (
            "Synthetic accounting and alert mechanics only; "
            "no market predictability or profit claim."
        ),
        "provenance": provenance(root, submission, metadata, split),
        "submission": submission, "bars": len(bars),
        "summary": simulation["summary"], "controls": controls,
        "alert_evaluation": evaluate_alerts(bars, decisions, lookback, submission["evaluation"]),
        "decisions": decisions, "fills": simulation["fills"],
        "equity_curve": simulation["equity_curve"],
    }


def development(root, submission_name, output):
    submission = load_submission(root, submission_name)
    metadata = manifest(root)
    bars = load_split(root, "development", metadata)
    report = build_report(root, submission, metadata, "development", bars)
    write_new(root, output, report)
    return report


def freeze(root, submission_name, development_name, output):
    submission = load_submission(root, submission_name)
    metadata = manifest(root)
    path = repo_path(root, development_name)
    report = load_json(path, MAX_REPORT_BYTES)
    expected = provenance(root, submission, metadata, "development")
    if (
        not isinstance(report, dict) or report.get("provenance") != expected
        or report.get("submission") != submission or report.get("evidence_level") != EVIDENCE
    ):
        raise LabError("development evidence must match this submission, source, and dataset")
    if repo_path(root, CONSUMED).exists():
        raise LabError("this dataset holdout has already been consumed")
    receipt = {
        "schema_version": 1, "kind": "frozen_synthetic_submission", "evidence_level": EVIDENCE,
        "submission": submission, "development_provenance": expected,
        "development_report": development_name,
        "development_report_sha256": digest(read_bytes(path, MAX_REPORT_BYTES)),
        "holdout_sha256": metadata["splits"]["holdout"]["sha256"],
    }
    receipt["receipt_sha256"] = object_hash(receipt)
    write_new(root, output, receipt)
    return receipt


def holdout(root, freeze_name, output):
    receipt = load_json(repo_path(root, freeze_name))
    required = {
        "schema_version", "kind", "evidence_level", "submission", "development_provenance",
        "development_report", "development_report_sha256", "holdout_sha256", "receipt_sha256",
    }
    if not isinstance(receipt, dict) or set(receipt) != required:
        raise LabError("invalid freeze receipt fields")
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if (
        receipt["receipt_sha256"] != object_hash(body) or receipt["schema_version"] != 1
        or receipt["kind"] != "frozen_synthetic_submission" or receipt["evidence_level"] != EVIDENCE
    ):
        raise LabError("invalid freeze receipt identity")
    submission = validate_submission(root, receipt["submission"])
    metadata = manifest(root)
    if receipt["development_provenance"] != provenance(root, submission, metadata, "development"):
        raise LabError("source, submission, or dataset changed after freeze")
    if receipt["holdout_sha256"] != metadata["splits"]["holdout"]["sha256"]:
        raise LabError("holdout identity changed after freeze")
    if type(receipt["development_report"]) is not str:
        raise LabError("development report path must be a string")
    evidence_path = repo_path(root, receipt["development_report"])
    if digest(read_bytes(evidence_path, MAX_REPORT_BYTES)) != receipt["development_report_sha256"]:
        raise LabError("development evidence changed after freeze")
    output_path = repo_path(root, output, output=True)
    if output_path.exists():
        raise LabError("output already exists; preserve evidence")
    # Claim globally per dataset, using exclusive creation, BEFORE reading holdout.
    # Any subsequent error leaves the attempt consumed. No reset operation exists.
    write_new(root, CONSUMED, {
        "schema_version": 1, "state": "consumed_before_evaluation",
        "dataset_id": DATASET_ID, "freeze_sha256": receipt["receipt_sha256"],
        "output": output, "evidence_level": EVIDENCE,
    })
    bars = load_split(root, "holdout", metadata)
    report = build_report(root, submission, metadata, "holdout", bars)
    report["freeze_sha256"] = receipt["receipt_sha256"]
    write_new(root, output, report)
    return report
