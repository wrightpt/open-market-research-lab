"""Bounded read/ack adapter over the existing job ledger, never a dispatcher."""
import json
import re
import shutil

from market_lab.io import canonical_bytes, object_hash, repo_path
from .ledger import MeterError
from .job_contract import MAX_STATE_BYTES, MIN_FREE_BYTES

CONSUMERS = frozenset({"research-ui", "workstation-handoff", "runtime-simulation"})
HASH = re.compile(r"[a-f0-9]{64}\Z")
ZERO = "0" * 64
PAGE_LIMIT = 32
STATES = {"reserved": "queued", "executing": "running",
          "cancel_requested": "cancelling", "settled": "succeeded"}


class JobEvents:
    """Observations in the SAME SQLite authority, never execution permissions.

    Events already commit atomically with job transitions in OfflineLedger.
    The finite job quota and three fixed consumers bound receipt growth.
    """
    def __init__(self, jobs):
        self.jobs = jobs
        with jobs.ledger.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS job_event_acks("
                       "tenant TEXT NOT NULL, consumer TEXT NOT NULL, ordinal INTEGER NOT NULL, "
                       "payload TEXT NOT NULL, previous_hash TEXT NOT NULL, receipt_hash TEXT NOT NULL, "
                       "PRIMARY KEY(tenant,consumer,ordinal))")
            for verb in ("UPDATE", "DELETE"):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS no_job_ack_{verb.lower()} "
                           f"BEFORE {verb} ON job_event_acks "
                           "BEGIN SELECT RAISE(ABORT,'append only'); END")
            self._verify(db)

    @staticmethod
    def _consumer(consumer):
        if type(consumer) is not str or consumer not in CONSUMERS:
            raise MeterError("unknown fixed event consumer")

    @staticmethod
    def _events(db, tenant):
        # Original ledger: at most eight tenants and 64 jobs each. Never expose
        # global sequence numbers or neighboring tenants' event payloads.
        return [{"event_id": r["event_hash"], "payload": p}
                for r in db.execute("SELECT payload,event_hash FROM events ORDER BY seq")
                if (p := json.loads(r["payload"]))["tenant"] == tenant]

    def _verify(self, db):
        self.verify_ledger(db, self.jobs.registry)

    @classmethod
    def verify_ledger(cls, db, registry):
        """Usable before controller startup/reconciliation, without an adapter."""
        streams = {}
        for row in db.execute("SELECT * FROM job_event_acks ORDER BY tenant,consumer,ordinal"):
            key = row["tenant"], row["consumer"]
            if key[0] not in registry.budgets or key[1] not in CONSUMERS:
                raise MeterError("acknowledgment has unknown owner")
            if key not in streams:
                streams[key] = [cls._events(db, key[0]), 0, ZERO]
            events, count, previous = streams[key]
            try:
                p = json.loads(row["payload"])
                fields = {"schema_version", "tenant", "consumer", "ordinal",
                          "event_id", "acknowledged_at_ms", "kind"}
                if (set(p) != fields or type(p["acknowledged_at_ms"]) is not int
                        or p["acknowledged_at_ms"] < 0
                        or p["schema_version"] != 1 or p["kind"] != "consumer_ack"
                        or p["tenant"] != key[0] or p["consumer"] != key[1]
                        or type(p["ordinal"]) is not int or p["ordinal"] != count + 1
                        or row["ordinal"] != count + 1 or count >= len(events)
                        or p["event_id"] != events[count]["event_id"]
                        or row["previous_hash"] != previous
                        or row["receipt_hash"] != object_hash({"previous_hash": previous, "payload": p})
                        or row["payload"] != canonical_bytes(p).decode()):
                    raise MeterError("acknowledgment evidence mismatch")
            except (TypeError, ValueError, KeyError) as exc:
                raise MeterError("invalid acknowledgment evidence") from exc
            streams[key][1:] = [count + 1, row["receipt_hash"]]

    @staticmethod
    def _project(event):
        p = event["payload"]
        return {"event_id": event["event_id"], "job_id": p["id"],
                "status": STATES.get(p["state"], p["state"]), "at_ms": p["at_ms"],
                "request_sha256": p["request_hash"], "source_sha256": p["source_hash"],
                "dataset_manifest_sha256": p["manifest_hash"],
                "result_sha256": p["result_hash"], "reason": p["reason"],
                "blocker": "execution_outcome_requires_review" if p["state"] == "uncertain" else None}

    @staticmethod
    def _receipt(row):
        p = json.loads(row["payload"])
        return {"kind": p["kind"], "consumer": p["consumer"], "event_id": p["event_id"],
                "acknowledged_at_ms": p["acknowledged_at_ms"],
                "receipt_sha256": row["receipt_hash"]}

    def read(self, principal, consumer, *, after=None, limit=16):
        tenant = self.jobs.registry.require(principal)
        self._consumer(consumer)
        if type(limit) is not int or not 1 <= limit <= PAGE_LIMIT:
            raise MeterError("event page exceeds bound")
        if after is not None and (type(after) is not str or
                                  (after != "start" and not HASH.fullmatch(after))):
            raise MeterError("invalid event cursor")
        with self.jobs._lock:
            self.jobs._verify_integrity()
            with self.jobs.ledger.transaction() as db:
                self._verify(db)
                events = self._events(db, tenant)
                ack = db.execute("SELECT * FROM job_event_acks WHERE tenant=? AND consumer=? "
                                 "ORDER BY ordinal DESC LIMIT 1", (tenant, consumer)).fetchone()
                cursor = after if after is not None else (json.loads(ack["payload"])["event_id"] if ack else "start")
                start = 0
                if cursor != "start":
                    found = [i for i, event in enumerate(events) if event["event_id"] == cursor]
                    if not found:
                        raise MeterError("event cursor unavailable")
                    start = found[0] + 1
                page = [self._project(e) for e in events[start:start + limit]]
                return {"schema_version": 1, "consumer": consumer, "events": page,
                        "next_cursor": page[-1]["event_id"] if page else cursor,
                        "has_more": start + len(page) < len(events),
                        "acknowledgment": self._receipt(ack) if ack else None,
                        "delivery": "at_least_once_until_explicit_ack", "native_dispatch": False}

    def _admit_ack(self):
        state = repo_path(self.jobs.root, self.jobs.directory, output=True)
        used = 0
        for path in state.rglob("*"):
            if path.is_symlink():
                raise MeterError("state symlink is not admitted")
            if path.is_file():
                used += path.stat().st_size
        if used + 16384 > MAX_STATE_BYTES or shutil.disk_usage(state).free < MIN_FREE_BYTES + 16384:
            raise MeterError("acknowledgment storage unavailable")

    def acknowledge(self, principal, consumer, event_id):
        tenant = self.jobs.registry.require(principal)
        self._consumer(consumer)
        if type(event_id) is not str or not HASH.fullmatch(event_id):
            raise MeterError("invalid event identity")
        with self.jobs._lock:
            self.jobs._verify_integrity()
            with self.jobs.ledger.transaction() as db:
                self._verify(db)
                events = self._events(db, tenant)
                found = [i for i, event in enumerate(events) if event["event_id"] == event_id]
                if not found:
                    raise MeterError("event unavailable")
                ordinal = found[0] + 1
                prior = db.execute("SELECT * FROM job_event_acks WHERE tenant=? AND consumer=? AND ordinal=?",
                                   (tenant, consumer, ordinal)).fetchone()
                if prior:
                    return self._receipt(prior)
                last = db.execute("SELECT * FROM job_event_acks WHERE tenant=? AND consumer=? "
                                  "ORDER BY ordinal DESC LIMIT 1", (tenant, consumer)).fetchone()
                if ordinal != (last["ordinal"] + 1 if last else 1):
                    raise MeterError("acknowledge contiguous events in order")
                self._admit_ack()
                previous = last["receipt_hash"] if last else ZERO
                payload = {"schema_version": 1, "tenant": tenant, "consumer": consumer,
                           "ordinal": ordinal, "event_id": event_id,
                           "acknowledged_at_ms": int(self.jobs.ledger.clock() * 1000), "kind": "consumer_ack"}
                hashed = object_hash({"previous_hash": previous, "payload": payload})
                db.execute("INSERT INTO job_event_acks VALUES(?,?,?,?,?,?)",
                           (tenant, consumer, ordinal, canonical_bytes(payload).decode(), previous, hashed))
                row = db.execute("SELECT * FROM job_event_acks WHERE tenant=? AND consumer=? AND ordinal=?",
                                 (tenant, consumer, ordinal)).fetchone()
                return self._receipt(row)

    def event(self, principal, event_id):
        """Resolve an exact retained own event, not a caller-provided payload."""
        tenant = self.jobs.registry.require(principal)
        if type(event_id) is not str or not HASH.fullmatch(event_id):
            raise MeterError("invalid event identity")
        with self.jobs._lock:
            self.jobs._verify_integrity()
            with self.jobs.ledger.transaction() as db:
                self._verify(db)
                for event in self._events(db, tenant):
                    if event["event_id"] == event_id:
                        return self._project(event)
        raise MeterError("event unavailable")
