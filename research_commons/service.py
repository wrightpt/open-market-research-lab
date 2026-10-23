"""Evidence transitions and development-only replay using the existing engine."""

import copy
import uuid

from market_lab.contract import validate_submission
from market_lab.data import load_split, manifest
from market_lab.io import LabError, canonical_bytes, load_json, object_hash, source_hash
from market_lab.research import EVIDENCE, build_report, provenance

from .journal import MAX_EVENTS, Journal

PERSONAS = {"researcher": "Local researcher", "reviewer": "Local reviewer"}
REPORT_FIELDS = {
    "schema_version", "evidence_level", "interpretation", "provenance", "submission",
    "bars", "summary", "controls", "alert_evaluation", "decisions", "fills", "equity_curve",
}


def text_field(value, name, minimum=1, maximum=2000):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise LabError(f"{name} must contain {minimum}–{maximum} characters")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise LabError(f"{name} contains control characters")
    return value.strip()


class Commons:
    def __init__(self, root, directory="artifacts/commons"):
        self.root = root
        self.engine_sha256 = source_hash(root)
        self.journal = Journal(root, directory)
        self.studies = {}
        try:
            for event in self.journal.events:
                self._apply(event)
            # There are no background workers: a retained start at boot was interrupted.
            for study in list(self.studies.values()):
                if study["status"] in {"running", "verifying"}:
                    started = next(e for e in reversed(self.journal.events)
                                   if e["study_id"] == study["id"])
                    self._append(started["actor"], "failed", study["id"],
                                 started["request_id"], started["request_sha256"],
                                 {"message": "Process stopped before completion; attempt retained."})
        except Exception:
            self.close()
            raise

    def close(self):
        self.journal.close()

    def _apply(self, event):
        kind, value, sid = event["kind"], event["payload"], event["study_id"]
        if kind == "created":
            self.studies[sid] = {
                "id": sid, "author": event["actor"], "created_at": event["at"],
                "status": "draft", "evidence": None, "reproduction": None,
                "reviews": [], "attempts": [], **copy.deepcopy(value),
            }
        study = self.studies[sid]
        study["updated_at"] = event["at"]
        if kind in {"run_started", "replay_started"}:
            study["status"] = "running" if kind == "run_started" else "verifying"
            study["attempts"].append({"kind": kind, "at": event["at"], "status": "started"})
        elif kind == "submitted":
            study["evidence"] = copy.deepcopy(value)
            study["status"] = "submitted"
            if study["attempts"] and study["attempts"][-1]["status"] == "started":
                study["attempts"][-1]["status"] = "completed"
        elif kind == "replayed":
            study["reproduction"] = {**copy.deepcopy(value), "actor": event["actor"], "at": event["at"]}
            study["status"] = "reproduced" if value["matched"] else "disputed"
            study["attempts"][-1]["status"] = "completed"
        elif kind == "failed":
            study["status"] = "failed"
            if study["attempts"]:
                study["attempts"][-1].update(status="failed", message=value["message"])
        elif kind == "reviewed":
            study["reviews"].append({**value, "actor": event["actor"], "at": event["at"]})

    def _append(self, *args):
        event = self.journal.append(*args)
        self._apply(event)
        return event

    def get(self, sid):
        if sid not in self.studies:
            raise LabError("study not found")
        return copy.deepcopy(self.studies[sid])

    def listing(self):
        result = []
        for study in reversed(list(self.studies.values())):
            result.append({k: copy.deepcopy(v) for k, v in study.items()
                           if k not in {"evidence", "reproduction", "attempts"}})
        return result

    def metadata(self):
        data = manifest(self.root)
        return {
            "mode": "local_synthetic", "evidence_level": EVIDENCE, "personas": PERSONAS,
            "baseline": load_json(self.root / "submissions/baseline.json"),
            "dataset": {"id": data["dataset_id"], "instrument": data["instrument"],
                        "development": data["splits"]["development"],
                        "license": "Apache-2.0 · original synthetic fixture",
                        "time_basis": "UTC bar close; next-row open execution",
                        "source_sha256": self.engine_sha256},
            "limits": {"events": MAX_EVENTS, "events_used": len(self.journal.events),
                       "report_bytes": 2_000_000},
        }

    def _report(self, study):
        if (source_hash(self.root) != self.engine_sha256
                or self.engine_sha256 != study["source_sha256"]):
            raise LabError("engine source changed after study creation; create a linked revision")
        submission = validate_submission(self.root, study["submission"])
        data = manifest(self.root)
        if object_hash(data) != study["manifest_sha256"]:
            raise LabError("dataset manifest changed after study creation")
        bars = load_split(self.root, "development", data)
        return build_report(self.root, submission, data, "development", bars)

    def _import_report(self, study, report):
        if not isinstance(report, dict) or set(report) != REPORT_FIELDS:
            raise LabError("import a complete market_lab development report JSON")
        expected = provenance(self.root, study["submission"], manifest(self.root), "development")
        if (report["evidence_level"] != EVIDENCE or report["schema_version"] != 1
                or expected["source_sha256"] != study["source_sha256"]
                or expected["source_sha256"] != self.engine_sha256
                or expected["manifest_sha256"] != study["manifest_sha256"]
                or report["provenance"] != expected
                or object_hash(report["submission"]) != object_hash(study["submission"])
                or report["bars"] != 384):
            raise LabError("report must bind this exact submission, source and development fixture")
        numeric = {"initial_cash", "final_equity", "net_return_fraction", "max_close_drawdown_fraction",
                   "fills", "round_trips", "fees_paid", "slippage_cost", "terminal_position_units"}
        summaries = [report["summary"]]
        if not isinstance(report["controls"], dict) or set(report["controls"]) != {
                "always_cash", "always_long_after_warmup"}:
            raise LabError("report control summaries are missing")
        summaries.extend(report["controls"].values())
        if any(not isinstance(s, dict) or set(s) != numeric or
               any(type(s[k]) not in (int, float) for k in numeric) for s in summaries):
            raise LabError("report summaries must contain finite numeric metrics")
        if any(not isinstance(report[k], list) for k in ("decisions", "fills", "equity_curve")):
            raise LabError("report must retain decision, fill and equity arrays")
        if (len(report["decisions"]) != 384 or len(report["equity_curve"]) != 384
                or len(report["fills"]) > 1000):
            raise LabError("report arrays must match the bounded development fixture")
        if not isinstance(report["alert_evaluation"], dict):
            raise LabError("report alert evaluation is missing")
        if len(canonical_bytes(report)) > 1_900_000:
            raise LabError("report is too large")
        # Values are deliberately NOT trusted as results until a full replay matches.
        return report

    def mutate(self, actor, action, sid, body, key):
        if actor not in PERSONAS or not isinstance(body, dict):
            raise LabError("invalid local persona or request object")
        fingerprint = object_hash({"action": action, "study_id": sid, "body": body})
        with self.journal.lock:
            existing = self.journal.receipt(actor, key, fingerprint)
            if existing:
                return self.get(existing["study_id"])
            if action == "create":
                if source_hash(self.root) != self.engine_sha256:
                    raise LabError("engine files changed while the server was running; restart before creating a study")
                if set(body) != {"submission", "parent_id"}:
                    raise LabError("create requires submission and parent_id")
                submission = validate_submission(self.root, body["submission"])
                parent = body["parent_id"]
                if parent is not None:
                    self.get(parent)
                if any(s["submission"]["submission_id"] == submission["submission_id"]
                       for s in self.studies.values()):
                    raise LabError("submission_id already exists; use a new revision identifier")
                sid = uuid.uuid4().hex[:16]
                self._append(actor, "created", sid, key, fingerprint, {
                    "submission": submission, "parent_id": parent,
                    "source_sha256": self.engine_sha256,
                    "manifest_sha256": object_hash(manifest(self.root)),
                })
                return self.get(sid)
            study = self.get(sid)
            if action == "review":
                if set(body) != {"verdict", "rationale", "conflicts"}:
                    raise LabError("review requires verdict, rationale and conflicts")
                if actor == study["author"]:
                    raise LabError("use the other local persona to exercise reviewer separation")
                if study["status"] not in {"reproduced", "disputed"}:
                    raise LabError("replay the report before recording a review")
                if body["verdict"] not in {"accepted", "needs_changes", "rejected"}:
                    raise LabError("unknown review verdict")
                if body["verdict"] == "accepted" and study["status"] != "reproduced":
                    raise LabError("a mismatched report cannot receive an accepted review")
                self._append(actor, "reviewed", sid, key, fingerprint, {
                    "verdict": body["verdict"],
                    "rationale": text_field(body["rationale"], "rationale", 20),
                    "conflicts": text_field(body["conflicts"], "conflicts", 5, 500),
                })
            elif action in {"run", "import", "reproduce"}:
                if action == "reproduce":
                    if actor == study["author"]:
                        raise LabError("switch to the other local persona for replay")
                    if study["evidence"] is None or study["reproduction"] is not None:
                        raise LabError("replay requires submitted evidence without a completed replay")
                elif actor != study["author"] or study["evidence"] is not None:
                    raise LabError("only the author can submit first evidence; fork to revise")
                if action == "import":
                    if set(body) != {"report"}:
                        raise LabError("import requires a report object")
                    report = self._import_report(study, body["report"])
                    self._append(actor, "submitted", sid, key, fingerprint,
                                 {"report": report, "sha256": object_hash(report), "origin": "imported"})
                else:
                    if body:
                        raise LabError("run and reproduce take an empty object")
                    if len(study["attempts"]) >= 10 or len(self.journal.events) + 2 > MAX_EVENTS:
                        raise LabError("local attempt or journal capacity reached")
                    self._append(actor, "replay_started" if action == "reproduce" else "run_started",
                                 sid, key, fingerprint, {})
                    try:
                        report = self._report(study)
                    except (LabError, OSError, ValueError):
                        self._append(actor, "failed", sid, key, fingerprint,
                                     {"message": "Engine or fixture validation failed; preserve this attempt and inspect local source."})
                    else:
                        digest = object_hash(report)
                        if action == "run":
                            self._append(actor, "submitted", sid, key, fingerprint,
                                         {"report": report, "sha256": digest, "origin": "local_engine"})
                        else:
                            claimed = study["evidence"]["report"]
                            differences = [k for k in report if object_hash(report[k]) != object_hash(claimed.get(k))]
                            self._append(actor, "replayed", sid, key, fingerprint, {
                                "matched": digest == study["evidence"]["sha256"],
                                "sha256": digest, "report": report, "differing_sections": differences,
                            })
            else:
                raise LabError("unknown operation")
            return self.get(sid)

    def export(self, sid):
        study = self.get(sid)
        return {
            "schema_version": 1, "kind": "commons_evidence_package", "evidence_level": EVIDENCE,
            "interpretation": "Local synthetic repeatability; personas are not independent identities.",
            "study": study,
            "history": [{k: v for k, v in e.items() if k not in {"payload", "request_id", "request_sha256"}}
                        for e in self.journal.events if e["study_id"] == sid],
            "study_sha256": object_hash(study),
        }

    def seed(self):
        """Two explicitly named examples, generated once with fixed parameters."""
        for index, title in enumerate(("Example · a reproducible baseline", "Example · a disputed report")):
            key = f"example-create-{index}"
            prior = next((e for e in self.journal.events if e["request_id"] == key), None)
            if prior:
                continue
            submission = load_json(self.root / "submissions/baseline.json")
            submission.update(title=title, submission_id=f"commons-example-{index}")
            study = self.mutate("researcher", "create", None,
                                {"submission": submission, "parent_id": None}, key)
            sid = study["id"]
            report = self._report(study)
            if index:
                report["summary"]["fees_paid"] += 1  # Deliberate fixture discrepancy.
            self.mutate("researcher", "import", sid, {"report": report}, f"example-evidence-{index}")
            self.mutate("reviewer", "reproduce", sid, {}, f"example-replay-{index}")
            self.mutate("reviewer", "review", sid, {
                "verdict": "rejected" if index else "accepted",
                "rationale": ("Example review: the reported fees differ from deterministic replay. Preserve both reports."
                              if index else "Example review: complete report matched the local engine. This establishes synthetic repeatability only."),
                "conflicts": "Seeded demonstration personas; no independent human review.",
            }, f"example-review-{index}")
