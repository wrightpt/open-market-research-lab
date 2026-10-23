"""Offline, synthetic-only metering. No real credits, users, wallets or HTTP routes."""
from __future__ import annotations

import fcntl
import json
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from market_lab.data import manifest
from market_lab.fixtures import DATASET_ID
from market_lab.io import LabError, canonical_bytes, object_hash, repo_path, source_hash
from market_lab.research import EVIDENCE

PRICES = {
    "synthetic_sample.v1": 2,      # 2 USD cents, fixture credit only
    "synthetic_backtest.v1": 50,   # 50 USD cents, fixture credit only
}
CATALOG_VERSION = 1
RESERVATION_TTL = 60
MAX_OPERATIONS = 64
MAX_ACTIVE = 2
KEY = re.compile(r"[A-Za-z0-9_-]{8,100}\Z")
TENANT = re.compile(r"[a-z][a-z0-9-]{2,39}\Z")


class MeterError(LabError):
    """A rejected synthetic metering operation."""


@dataclass(frozen=True)
class FixturePrincipal:
    tenant_id: str
    _seal: str


class FixtureRegistry:
    """Trusted test fixture identities only; this is NOT user authentication."""

    def __init__(self, budgets=None):
        self.budgets = dict(budgets if budgets is not None
                            else {"demo-alpha": 200, "demo-beta": 200})
        if not 1 <= len(self.budgets) <= 8 or any(
            not TENANT.fullmatch(name) or type(cents) is not int
            or not 1 <= cents <= 100_000
            for name, cents in self.budgets.items()
        ):
            raise MeterError("invalid fixture registry")
        self._seal = secrets.token_hex(32)

    def issue(self, tenant_id):
        if tenant_id not in self.budgets:
            raise MeterError("fixture identity unknown")
        return FixturePrincipal(tenant_id, self._seal)

    def require(self, principal):
        if (not isinstance(principal, FixturePrincipal)
                or principal.tenant_id not in self.budgets
                or not secrets.compare_digest(principal._seal, self._seal)):
            raise MeterError("verified in-process fixture principal required")
        return principal.tenant_id


def validated(sku, params):
    if sku not in PRICES or type(params) is not dict:
        raise MeterError("unrecognized or malformed synthetic SKU")
    if sku == "synthetic_sample.v1":
        if (set(params) != {"offset", "limit"}
                or type(params["offset"]) is not int or type(params["limit"]) is not int
                or not 0 <= params["offset"] < 384 or not 1 <= params["limit"] <= 20
                or params["offset"] + params["limit"] > 384):
            raise MeterError("only 1–20 development fixture bars can be sampled")
    elif params != {}:
        raise MeterError("fixed synthetic backtest takes no arguments")
    return PRICES[sku]


class OfflineLedger:
    """Single-process durable SQLite state machine with append-only hashed events.

    BEGIN IMMEDIATE serializes thread-level reservations, while a POSIX lock
    prevents a second process from mutating this ledger during execution.
    An interrupted 'executing' operation becomes 'uncertain', never rerun.
    """

    def __init__(self, root: Path, registry: FixtureRegistry, *,
                 directory="artifacts/offline-metering", clock=None):
        self.root = Path(root)
        self.registry = registry
        self.clock = clock if clock is not None else time.time
        self.directory = directory
        self.db_path = repo_path(self.root, f"{directory}/ledger.sqlite3", output=True)
        lock = repo_path(self.root, f"{directory}/writer.lock", output=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = lock.open("a+b")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._initialize()
            self.verify_audit()
            self.reconcile()
        except BaseException:
            self.close()
            raise

    def close(self):
        if not self._lock.closed:
            fcntl.flock(self._lock, fcntl.LOCK_UN)
            self._lock.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.db_path, isolation_level=None, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self):
        statements = (
            "CREATE TABLE IF NOT EXISTS tenants("
            "tenant_id TEXT PRIMARY KEY, budget_cents INTEGER NOT NULL)",
            "CREATE TABLE IF NOT EXISTS operations("
            "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id), "
            "request_key TEXT NOT NULL, sku TEXT NOT NULL, params TEXT NOT NULL, "
            "request_hash TEXT NOT NULL, source_hash TEXT NOT NULL, manifest_hash TEXT NOT NULL, "
            "price_cents INTEGER NOT NULL, state TEXT NOT NULL, created REAL NOT NULL, "
            "expires REAL NOT NULL, result_hash TEXT, result_json TEXT, failure TEXT, "
            "UNIQUE(tenant_id,request_key))",
            "CREATE TABLE IF NOT EXISTS events("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL, "
            "previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL)",
            "CREATE TRIGGER IF NOT EXISTS no_event_update BEFORE UPDATE ON events "
            "BEGIN SELECT RAISE(ABORT,'append only'); END",
            "CREATE TRIGGER IF NOT EXISTS no_event_delete BEFORE DELETE ON events "
            "BEGIN SELECT RAISE(ABORT,'append only'); END",
        )
        with self.transaction() as db:
            for statement in statements:
                db.execute(statement)
            for name, budget in self.registry.budgets.items():
                row = db.execute("SELECT budget_cents FROM tenants WHERE tenant_id=?",
                                 (name,)).fetchone()
                if row is None:
                    db.execute("INSERT INTO tenants VALUES(?,?)", (name, budget))
                elif row["budget_cents"] != budget:
                    raise MeterError("existing fixture budget cannot be silently changed")
            stored = {r["tenant_id"] for r in db.execute("SELECT tenant_id FROM tenants")}
            if stored != set(self.registry.budgets):
                raise MeterError("ledger belongs to a different fixture registry")

    def _event(self, db, row, reason=None):
        payload = {
            "id": row["id"], "tenant": row["tenant_id"],
            "request_hash": row["request_hash"], "sku": row["sku"],
            "price_cents": row["price_cents"], "state": row["state"],
            "source_hash": row["source_hash"], "manifest_hash": row["manifest_hash"],
            "result_hash": row["result_hash"], "reason": reason,
            "at_ms": int(self.clock() * 1000),
        }
        last = db.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        previous = last[0] if last else "0" * 64
        hashed = object_hash({"previous_hash": previous, "payload": payload})
        db.execute("INSERT INTO events(payload,previous_hash,event_hash) VALUES(?,?,?)",
                   (canonical_bytes(payload).decode(), previous, hashed))

    def verify_audit(self):
        with self.transaction() as db:
            previous = "0" * 64
            projected = {}
            for entry in db.execute("SELECT * FROM events ORDER BY seq"):
                try:
                    payload = json.loads(entry["payload"])
                    hashed = object_hash({"previous_hash": previous, "payload": payload})
                except (ValueError, TypeError) as exc:
                    raise MeterError("invalid ledger audit content") from exc
                if entry["previous_hash"] != previous or entry["event_hash"] != hashed:
                    raise MeterError("ledger audit digest mismatch; preserve evidence")
                previous = hashed
                projected[payload["id"]] = payload
            actual = list(db.execute("SELECT * FROM operations"))
            if set(projected) != {row["id"] for row in actual}:
                raise MeterError("ledger operation set differs from audit")
            for row in actual:
                recorded = projected[row["id"]]
                fields = (("tenant", "tenant_id"), ("request_hash", "request_hash"),
                          ("sku", "sku"), ("price_cents", "price_cents"),
                          ("state", "state"), ("result_hash", "result_hash"),
                          ("source_hash", "source_hash"),
                          ("manifest_hash", "manifest_hash"))
                if any(recorded[key] != row[column] for key, column in fields
                       if key in recorded):
                    raise MeterError("ledger receipt differs from audit")
        return True

    @staticmethod
    def _row(db, tenant, operation_id):
        row = db.execute("SELECT * FROM operations WHERE tenant_id=? AND id=?",
                         (tenant, operation_id)).fetchone()
        if row is None:
            raise MeterError("receipt unavailable to fixture tenant")
        return row

    @staticmethod
    def _receipt(row):
        return {
            "mode": "offline_fixture_no_real_funds", "id": row["id"],
            "sku": row["sku"], "price_cents": row["price_cents"],
            "catalog_version": CATALOG_VERSION, "state": row["state"],
            "charged_cents": row["price_cents"] if row["state"] == "settled" else 0,
            "request_sha256": row["request_hash"],
            "source_sha256": row["source_hash"],
            "manifest_sha256": row["manifest_hash"],
            "evidence_sha256": row["result_hash"],
            "failure": row["failure"],
            "created_at": row["created"], "expires_at": row["expires"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "evidence_level": EVIDENCE,
        }

    @staticmethod
    def _balance(db, tenant):
        record = db.execute("""
            SELECT t.budget_cents,
            COALESCE(SUM(CASE WHEN o.state='settled' THEN o.price_cents ELSE 0 END),0) spent,
            COALESCE(SUM(CASE WHEN o.state IN ('reserved','executing')
                           THEN o.price_cents ELSE 0 END),0) held,
            COUNT(o.id) used,
            COALESCE(SUM(CASE WHEN o.state IN ('reserved','executing') THEN 1 ELSE 0 END),0) active
            FROM tenants t LEFT JOIN operations o ON o.tenant_id=t.tenant_id
            WHERE t.tenant_id=? GROUP BY t.tenant_id
        """, (tenant,)).fetchone()
        return {
            "budget_cents": record["budget_cents"], "spent_cents": record["spent"],
            "held_cents": record["held"],
            "available_cents": record["budget_cents"] - record["spent"] - record["held"],
            "operations": record["used"], "active": record["active"],
        }

    def balance(self, principal):
        tenant = self.registry.require(principal)
        with self.transaction() as db:
            return self._balance(db, tenant)

    def _identity(self):
        metadata = manifest(self.root)
        if metadata["dataset_id"] != DATASET_ID or metadata["synthetic"] is not True:
            raise MeterError("source not admitted as the original synthetic fixture")
        return source_hash(self.root), object_hash(metadata)

    @staticmethod
    def _hash(sku, params):
        return object_hash({"version": CATALOG_VERSION, "sku": sku, "params": params})

    def quote(self, principal, sku, params):
        tenant = self.registry.require(principal)
        price = validated(sku, params)
        source, manifest_sha = self._identity()
        with self.transaction() as db:
            available = self._balance(db, tenant)["available_cents"]
        return {
            "mode": "offline_fixture_no_real_funds", "sku": sku,
            "catalog_version": CATALOG_VERSION, "price_cents": price,
            "request_sha256": self._hash(sku, params), "source_sha256": source,
            "manifest_sha256": manifest_sha, "available_cents": available,
            "evidence_level": EVIDENCE,
        }

    def get(self, principal, operation_id):
        tenant = self.registry.require(principal)
        with self.transaction() as db:
            return self._receipt(self._row(db, tenant, operation_id))

    def events(self, principal, operation_id):
        self.get(principal, operation_id)
        with self.transaction() as db:
            result = []
            for row in db.execute("SELECT * FROM events ORDER BY seq"):
                payload = json.loads(row["payload"])
                if payload["id"] == operation_id:
                    result.append({"seq": row["seq"], "event_sha256": row["event_hash"],
                                   **payload})
            return result

    def _transition(self, db, row, new, reason=None, *, result=None, digest=None):
        allowed = {
            "reserved": {"executing", "cancelled", "expired"},
            "executing": {"settled", "failed", "uncertain"},
            "settled": {"refunded"},
        }
        if new not in allowed.get(row["state"], set()):
            raise MeterError("invalid ledger transition")
        result_json = canonical_bytes(result).decode() if result is not None else row["result_json"]
        if result_json and len(result_json.encode()) > 32_768:
            raise MeterError("result exceeds metering receipt bound")
        db.execute(
            "UPDATE operations SET state=?,result_hash=?,result_json=?,failure=? WHERE id=?",
            (new, digest or row["result_hash"], result_json, reason, row["id"]))
        updated = db.execute("SELECT * FROM operations WHERE id=?", (row["id"],)).fetchone()
        self._event(db, updated, reason)
        return self._receipt(updated)

    def reserve(self, principal, key, sku, params):
        tenant = self.registry.require(principal)
        if type(key) is not str or not KEY.fullmatch(key):
            raise MeterError("invalid 8-100 character idempotency key")
        price = validated(sku, params)
        request_hash = self._hash(sku, params)
        with self.transaction() as db:
            prior = db.execute(
                "SELECT * FROM operations WHERE tenant_id=? AND request_key=?",
                (tenant, key)).fetchone()
            if prior:
                if prior["request_hash"] != request_hash:
                    raise MeterError("idempotency key binds a different request")
                return self._receipt(prior)
            source, identity = self._identity()
            funds = self._balance(db, tenant)
            if funds["operations"] >= MAX_OPERATIONS:
                raise MeterError("fixture operation quota exhausted")
            if funds["active"] >= MAX_ACTIVE:
                raise MeterError("too many active fixture reservations")
            if funds["available_cents"] < price:
                raise MeterError("insufficient simulated budget")
            now = self.clock()
            operation_id = uuid.uuid4().hex
            db.execute("""
                INSERT INTO operations(id,tenant_id,request_key,sku,params,request_hash,
                    source_hash,manifest_hash,price_cents,state,created,expires)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """, (operation_id, tenant, key, sku, canonical_bytes(params).decode(),
                  request_hash, source, identity, price, "reserved", now,
                  now + RESERVATION_TTL))
            row = self._row(db, tenant, operation_id)
            self._event(db, row)
            return self._receipt(row)

    def begin(self, principal, operation_id):
        tenant = self.registry.require(principal)
        with self.transaction() as db:
            row = self._row(db, tenant, operation_id)
            if row["state"] != "reserved":
                return self._receipt(row), False
            if self.clock() >= row["expires"]:
                return self._transition(db, row, "expired", "reservation_ttl"), False
            try:
                if self._identity() != (row["source_hash"], row["manifest_hash"]):
                    raise MeterError("source has changed")
            except (LabError, OSError):
                return self._transition(db, row, "cancelled", "source_drift"), False
            return self._transition(db, row, "executing"), True

    def finish(self, principal, operation_id, state, *, reason=None, result=None, digest=None):
        if state not in {"settled", "failed", "cancelled", "refunded"}:
            raise MeterError("disallowed public finish state")
        tenant = self.registry.require(principal)
        with self.transaction() as db:
            row = self._row(db, tenant, operation_id)
            if row["state"] == state:
                return self._receipt(row)
            if state == "settled" and (
                result is None or type(digest) is not str or not re.fullmatch("[a-f0-9]{64}", digest)
            ):
                raise MeterError("settlement needs a bounded result and evidence SHA-256")
            return self._transition(db, row, state, reason, result=result, digest=digest)

    def expire(self):
        with self.transaction() as db:
            for row in db.execute("SELECT * FROM operations WHERE state='reserved'").fetchall():
                if row["expires"] <= self.clock():
                    self._transition(db, row, "expired", "reservation_ttl")

    def reconcile(self):
        """On startup, never replay in-flight side effects or charge uncertain work."""
        with self.transaction() as db:
            active = db.execute(
                "SELECT * FROM operations WHERE state IN ('executing','reserved')").fetchall()
            for row in active:
                if row["state"] == "executing":
                    self._transition(db, row, "uncertain", "interrupted_after_claim")
                elif row["expires"] <= self.clock():
                    self._transition(db, row, "expired", "reservation_ttl")
