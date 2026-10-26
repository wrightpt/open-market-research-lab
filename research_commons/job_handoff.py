"""Pure simulation contracts; no transport, task-store writes or dispatch."""
from market_lab.io import object_hash
from .ledger import MeterError

TARGETS = frozenset({"beads", "gas-city", "strategy-experiment-runtime"})
GATES = (
    "canonical_project_admission", "exact_task_owner", "backup_restore_verified",
    "independent_source_review", "resource_and_dataset_admission", "operator_activation",
)


def preview_handoff(jobs, principal, event_id, target):
    """Proposed adapter envelope, NOT another product's native wire protocol.

    Every production gate remains unsatisfied. No boolean or request field can
    turn this digest-only preview into live authority.
    """
    if type(target) is not str or target not in TARGETS:
        raise MeterError("unrecognized handoff target")
    event = jobs.events.event(principal, event_id)
    if event["status"] not in {"succeeded", "failed", "cancelled", "expired", "uncertain", "refunded"}:
        raise MeterError("handoff requires a terminal or uncertain outcome")
    result = None
    if event["status"] in {"succeeded", "refunded"}:
        result = jobs.result_manifest(principal, event["job_id"])["manifest_sha256"]
    payload = {"schema_version": 1, "target": target, "event_id": event_id,
               "job_id": event["job_id"], "status": event["status"],
               "request_sha256": event["request_sha256"], "source_sha256": event["source_sha256"],
               "result_manifest_sha256": result, "blocker": event["blocker"],
               "authority": "synthetic_proposal_only", "native_dispatch": False,
               "missing_gates": list(GATES)}
    return {"proposal": payload, "proposal_sha256": object_hash(payload)}
