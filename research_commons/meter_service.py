"""Fixed synthetic research SKUs behind an offline fixture-credit ledger.

This module is NOT mounted on the Commons HTTP server or MCP gateway.
"""
from dataclasses import asdict

from market_lab.data import load_split, manifest
from market_lab.io import LabError, canonical_bytes, load_json, object_hash
from market_lab.research import EVIDENCE

from .ledger import MeterError
from .service import Commons


class OfflineResearchService:
    """Meter only fixed, internally selected operations; never arbitrary code."""

    def __init__(self, ledger):
        self.ledger = ledger

    def quote(self, principal, sku, params):
        return self.ledger.quote(principal, sku, params)

    def _dispatch(self, tenant, key, sku, params):
        root = self.ledger.root
        metadata = manifest(root)
        if sku == "synthetic_sample.v1":
            rows = load_split(root, "development", metadata)
            subset = rows[params["offset"]:params["offset"] + params["limit"]]
            result = {
                "sku": sku, "dataset_id": metadata["dataset_id"],
                "split": "development", "rows": [asdict(item) for item in subset],
                "evidence_level": EVIDENCE,
            }
            return result, object_hash(result)

        # This is deliberately a SINGLE fixed engine/submission, not a hosted
        # code runner. Every attempt is recorded by the existing Commons journal.
        identity = object_hash({"fixture_tenant": tenant, "request_key": key})
        commons = Commons(root, f"{self.ledger.directory}/commons")
        try:
            submission = load_json(root / "submissions/baseline.json")
            submission["submission_id"] = "meter-" + identity[:24]
            submission["title"] = "Offline metered fixed synthetic development run"
            created = commons.mutate(
                "researcher", "create", None,
                {"submission": submission, "parent_id": None},
                "create-" + identity[:32],
            )
            run = commons.mutate(
                "researcher", "run", created["id"], {}, "run-" + identity[:32],
            )
            if run["status"] != "submitted" or not run["evidence"]:
                raise MeterError("synthetic development run did not complete")
            replay = commons.mutate(
                "reviewer", "reproduce", run["id"], {}, "replay-" + identity[:32],
            )
            if replay["status"] != "reproduced" or not replay["reproduction"]["matched"]:
                raise MeterError("complete same-engine synthetic replay did not match")
            evidence = run["evidence"]
            result = {
                "sku": sku, "study_id": run["id"],
                "report_sha256": evidence["sha256"],
                "replay_sha256": replay["reproduction"]["sha256"],
                "replay_matched": True,
                "replay_kind": "same_engine_local_repeatability_not_independent_review",
                "summary": evidence["report"]["summary"],
                "dataset_id": metadata["dataset_id"],
                "split": "development", "evidence_level": EVIDENCE,
            }
            return result, evidence["sha256"]
        finally:
            commons.close()

    def purchase_fixture(self, principal, key, sku, params):
        """Quote/reserve/claim/execute/settle exactly once for fixture credits.

        A retry of a prior key reports the retained state/result; it NEVER
        replays execution or payments. Unknown failures release the reservation
        without falsely claiming an execution result.
        """
        tenant = self.ledger.registry.require(principal)
        receipt = self.ledger.reserve(principal, key, sku, params)
        if receipt["state"] != "reserved":
            return receipt
        receipt, acquired = self.ledger.begin(principal, receipt["id"])
        if not acquired:
            return receipt
        try:
            if self.ledger._identity() != (
                receipt["source_sha256"], receipt["manifest_sha256"]
            ):
                raise MeterError("fixture changed between claim and execution")
            result, digest = self._dispatch(tenant, key, sku, params)
            if len(canonical_bytes(result)) > 32_768:
                raise MeterError("result exceeds receipt budget")
        except Exception:
            return self.ledger.finish(
                principal, receipt["id"], "failed", reason="execution_failed"
            )
        # A failed/unknown durable commit must not be retried as a new job.
        return self.ledger.finish(
            principal, receipt["id"], "settled", result=result, digest=digest
        )
