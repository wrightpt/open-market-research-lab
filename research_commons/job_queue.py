"""Thin local job adapter over OfflineLedger; no engineering-task orchestration."""
import json
import os
import selectors
import shutil
import subprocess
import sys
import threading
import time

from market_lab.data import manifest
from market_lab.io import (LabError, canonical_bytes, object_hash, read_bytes,
                           repo_path, write_new, _check_tree, _unique_pairs)
from market_lab.research import EVIDENCE, provenance
from .ledger import OfflineLedger, FixtureRegistry, MeterError, PRICES
from .job_contract import (SKU, LIMITS, MAX_GLOBAL_ACTIVE, MAX_STATE_BYTES,
                           MIN_FREE_BYTES, validate_job, job_source_hash, catalog)


class JobLedger(OfflineLedger):
    def balance(self, principal):
        self.verify_audit()
        return super().balance(principal)

    def _validated(self, sku, params):
        if sku != SKU:
            raise MeterError("only the configuration-only synthetic job SKU is admitted")
        validate_job(self.root, params)
        return PRICES["synthetic_backtest.v1"]

    def _identity(self):
        _, manifest_sha = super()._identity()
        return job_source_hash(self.root), manifest_sha


class JobService:
    """One controller, one child, two reservations per tenant, no automatic replay.

    The ledger's exclusive OS lock fences other controllers across process
    restarts. The runtime Event wakes on accepted submissions/cancellations;
    a bounded 250ms reconciliation also catches lost in-process wakeups and TTLs.
    """
    def __init__(self, root, *, directory="artifacts/research-jobs", registry=None,
                 clock=None, entitlements=None):
        self.registry = registry or FixtureRegistry()
        self.ledger = JobLedger(root, self.registry, directory=directory, clock=clock)
        try:
            self.root = self.ledger.root
            self.directory = directory
            dataset = manifest(root)["dataset_id"]
            self.entitlements = ({tenant: {dataset} for tenant in self.registry.budgets}
                                 if entitlements is None else entitlements)
            self._lock = threading.RLock()
            self._runner = threading.Lock()
            self._wake = threading.Event()
            self._stop = threading.Event()
            self._thread = None
            self._fatal = None
            with self.ledger.transaction() as db:
                db.execute("CREATE TABLE IF NOT EXISTS job_control("
                           "id INTEGER PRIMARY KEY CHECK(id=1),paused INTEGER NOT NULL)")
                db.execute("INSERT OR IGNORE INTO job_control VALUES(1,0)")
                if db.execute("SELECT 1 FROM operations WHERE state='uncertain'").fetchone():
                    db.execute("UPDATE job_control SET paused=1 WHERE id=1")
            for tenant in self.registry.budgets:
                principal = self.registry.issue(tenant)
                for receipt in self.listing(principal):
                    if receipt["state"] in {"settled", "refunded"}:
                        self.result(principal, receipt["id"])
            from .job_events import JobEvents
            self.events = JobEvents(self)
        except BaseException:
            self.ledger.close()
            raise

    def _allow(self, principal):
        tenant = self.registry.require(principal)
        dataset = manifest(self.root)["dataset_id"]
        if dataset not in self.entitlements.get(tenant, set()):
            raise MeterError("dataset is not entitled")
        return tenant

    def quote(self, principal, spec):
        self._allow(principal)
        self.ledger.verify_audit()
        return self.ledger.quote(principal, SKU, spec)

    def _storage_admission(self):
        state = repo_path(self.root, self.directory, output=True)
        used = 0
        for path in state.rglob("*"):
            if path.is_symlink():
                raise MeterError("state symlink is not admitted")
            if path.is_file():
                used += path.stat().st_size
        with self.ledger.transaction() as db:
            active = db.execute("SELECT COUNT(*) FROM operations WHERE "
                                "state IN ('reserved','executing','cancel_requested')").fetchone()[0]
        # Reserve the maximum result plus bounded ledger/event overhead per job.
        reservation = LIMITS["output_bytes"] + 65536
        if (active >= MAX_GLOBAL_ACTIVE or used + (active + 1) * reservation > MAX_STATE_BYTES
                or shutil.disk_usage(state).free < MIN_FREE_BYTES + (active + 1) * reservation):
            raise MeterError("aggregate resource or storage admission exhausted")

    def submit(self, principal, key, spec):
        with self._lock:
            tenant = self._allow(principal)
            self.ledger.verify_audit()
            with self.ledger.transaction() as db:
                prior = db.execute("SELECT id FROM operations WHERE tenant_id=? AND request_key=?",
                                   (tenant, key)).fetchone()
            # An exact retry must remain observable even when admission is paused/full.
            if prior:
                return self._view(self.ledger.reserve(principal, key, SKU, spec))
            if self.health()["paused"] or self._stop.is_set():
                raise MeterError("job admission paused")
            self._storage_admission()
            receipt = self.ledger.reserve(principal, key, SKU, spec)
            self._wake.set()
            return self._view(receipt)

    @staticmethod
    def _view(receipt):
        status = {"reserved": "queued", "executing": "running",
                  "cancel_requested": "cancelling", "settled": "succeeded"}
        return {**receipt, "job_id": receipt["id"],
                "status": status.get(receipt["state"], receipt["state"])}

    def get(self, principal, job_id):
        with self._lock:
            self.ledger.verify_audit()
            return self._view(self.ledger.get(principal, job_id))

    def listing(self, principal):
        tenant = self.registry.require(principal)
        self.ledger.verify_audit()
        with self._lock, self.ledger.transaction() as db:
            rows = db.execute("SELECT * FROM operations WHERE tenant_id=? ORDER BY created,id LIMIT 64",
                              (tenant,)).fetchall()
            return [self._view(self.ledger._receipt(row)) for row in rows]

    def history(self, principal, job_id):
        with self._lock:
            self.ledger.verify_audit()
            return self.ledger.events(principal, job_id)

    def result(self, principal, job_id):
        with self._lock:
            receipt = self.get(principal, job_id)  # authorize BEFORE file access
            if receipt["state"] not in {"settled", "refunded"}:
                raise MeterError("result not available")
            tenant = self.registry.require(principal)
            path = repo_path(self.root, f"{self.directory}/results/{tenant}/{job_id}.json")
            report = json.loads(read_bytes(path, LIMITS["output_bytes"]), object_pairs_hook=_unique_pairs)
            _check_tree(report)
            if object_hash(report) != receipt["evidence_sha256"]:
                raise MeterError("result evidence digest mismatch")
            return report

    def cancel(self, principal, job_id):
        tenant = self.registry.require(principal)
        with self._lock:
            self.ledger.verify_audit()
            with self.ledger.transaction() as db:
                row = self.ledger._row(db, tenant, job_id)
                if row["state"] == "reserved":
                    receipt = self.ledger._transition(db, row, "cancelled", "cancelled_before_execution")
                elif row["state"] == "executing":
                    receipt = self.ledger._transition(db, row, "cancel_requested", "cancellation_requested")
                else:
                    receipt = self.ledger._receipt(row)
            self._wake.set()
            return self._view(receipt)

    def result_manifest(self, principal, job_id):
        """Stable evidence projection; never mint a completion or charge."""
        with self._lock:
            report = self.result(principal, job_id)
            receipt = self.get(principal, job_id)
            tenant = self.registry.require(principal)
            with self.ledger.transaction() as db:
                spec = json.loads(self.ledger._row(db, tenant, job_id)["params"])
            execution = receipt["result"]
            value = {"schema_version": 1, "job_id": job_id,
                     "evidence_level": "synthetic_engineering_only",
                     "input_sha256": object_hash(spec), "request_sha256": receipt["request_sha256"],
                     "code_revision": {"kind": "content_sha256", "value": receipt["source_sha256"]},
                     "model_revision": None, "model_note": "fixed_strategy_no_model",
                     "dataset_manifest_sha256": receipt["manifest_sha256"],
                     "provenance": report["provenance"],
                     "result_sha256": receipt["evidence_sha256"],
                     "execution_evidence_sha256": object_hash(execution),
                     "requested_resources": spec["resources"],
                     "observed_resources": {k: execution[k] for k in
                                            ("cpu_seconds", "max_rss_kib", "wall_seconds")},
                     "enforcement": execution["enforcement"],
                     "replay_kind": execution["replay_kind"]}
            return {"manifest": value, "manifest_sha256": object_hash(value)}

    def operator_snapshot(self):
        """Trusted in-process API only; never exposed by a tenant HTTP route."""
        with self._lock:
            self.ledger.verify_audit()
            with self.ledger.transaction() as db:
                self.events._verify(db)
                blockers = [{"job_id": r["id"], "reason": r["failure"],
                             "required_action": "independent_execution_reconciliation"}
                            for r in db.execute("SELECT id,failure FROM operations WHERE state='uncertain'")]
            return {**self.health(), "blockers": blockers, "native_dispatch": False,
                    "task_authority": "unchanged"}

    def refund(self, principal, job_id):
        with self._lock:
            self.ledger.verify_audit()
            return self._view(self.ledger.finish(principal, job_id, "refunded", reason="synthetic_refund"))

    def health(self):
        with self._lock, self.ledger.transaction() as db:
            paused = bool(db.execute("SELECT paused FROM job_control WHERE id=1").fetchone()[0])
            counts = {r[0]: r[1] for r in db.execute("SELECT state,COUNT(*) FROM operations GROUP BY state")}
        return {"paused": paused or bool(counts.get("uncertain")) or self._fatal is not None, "states": counts,
                "controller_error": self._fatal, "worker_slots": 1,
                "mode": "synthetic_source_prototype"}

    def pause(self):
        with self._lock, self.ledger.transaction() as db:
            db.execute("UPDATE job_control SET paused=1 WHERE id=1")

    def resume(self):
        with self._lock, self.ledger.transaction() as db:
            if self._fatal or db.execute("SELECT 1 FROM operations WHERE state='uncertain'").fetchone():
                raise MeterError("uncertain execution requires evidence-backed operator reconciliation")
            db.execute("UPDATE job_control SET paused=0 WHERE id=1")
        self._wake.set()

    def _next(self):
        with self._lock:
            self.ledger.verify_audit()
            self.ledger.expire()
            if self.health()["paused"] or self._stop.is_set():
                return None
            with self.ledger.transaction() as db:
                pending = [dict(r) for r in db.execute("SELECT * FROM operations WHERE state='reserved'")]
                last = {}
                for r in db.execute("SELECT seq,payload FROM events ORDER BY seq"):
                    event = json.loads(r["payload"])
                    if event["state"] == "executing":
                        last[event["tenant"]] = r["seq"]
            # Least recently served tenant, then FIFO within that tenant. The
            # history survives restart; a noisy tenant cannot reset its priority.
            pending.sort(key=lambda r: (last.get(r["tenant_id"], 0), r["created"], r["id"]))
            if not pending:
                return None
            row = pending[0]
            principal = self.registry.issue(row["tenant_id"])
            try:
                self._allow(principal)
            except MeterError:
                self.ledger.finish(principal, row["id"], "cancelled", reason="dataset_entitlement_revoked")
                return {"skipped": True}
            receipt, acquired = self.ledger.begin(principal, row["id"])
            if not acquired:
                return {"skipped": True}
            return {"row": row, "receipt": receipt, "principal": principal}

    def _command(self):
        # Only this fixed trusted module is executed. No caller command, URL,
        # image name, path or Python expression is accepted by the job contract.
        code = "import sys;sys.path.insert(0," + repr(str(self.root.resolve())) + ");" \
               "from research_commons.job_worker import main;main()"
        return [sys.executable, "-I", "-S", "-B", "-u", "-c", code]

    @staticmethod
    def _stop_child(process):
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return False
        return True

    def _execute(self, item):
        row, receipt, principal = item["row"], item["receipt"], item["principal"]
        spec = json.loads(row["params"])
        request = {"spec": spec, "source_sha256": receipt["source_sha256"],
                   "manifest_sha256": receipt["manifest_sha256"], "parent_pid": os.getpid()}
        process = None
        output = bytearray()
        reason = None
        began = time.monotonic()
        try:
            process = subprocess.Popen(self._command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True,
                                       cwd=self.root, env={"LC_ALL": "C.UTF-8"})
            request_bytes = canonical_bytes(request)
            written = 0
            os.set_blocking(process.stdin.fileno(), False)
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                selector.register(process.stdin, selectors.EVENT_WRITE)
                eof = False
                while True:
                    with self._lock:
                        state = self.ledger.get(principal, row["id"])["state"]
                    if state == "cancel_requested" or self._stop.is_set():
                        reason = "cancelled_after_worker_stop"
                        break
                    if time.monotonic() - began >= spec["resources"]["wall_seconds"]:
                        reason = "wall_limit_exceeded"
                        break
                    ready = selector.select(0.02)
                    for key, _ in ready:
                        if key.fileobj is process.stdin:
                            try:
                                written += os.write(process.stdin.fileno(), request_bytes[written:written + 4096])
                            except BlockingIOError:
                                continue
                            if written == len(request_bytes):
                                selector.unregister(process.stdin)
                                process.stdin.close()
                        else:
                            chunk = os.read(process.stdout.fileno(), 16384)
                            if not chunk:
                                eof = True
                                break
                            output.extend(chunk)
                            if len(output) > spec["resources"]["output_bytes"]:
                                reason = "output_limit_exceeded"
                                break
                    if eof or reason:
                        break
            if reason is None:
                try:
                    process.wait(timeout=max(0.01, spec["resources"]["wall_seconds"] - (time.monotonic() - began)))
                except subprocess.TimeoutExpired:
                    reason = "wall_limit_exceeded"
            if reason is not None and not self._stop_child(process):
                raise RuntimeError("worker termination could not be proven")
            if reason is None and process.returncode != 0:
                reason = "worker_failed_or_resource_limit"
        except (OSError, ValueError) as exc:
            reason = "worker_start_or_protocol_failure"
            if process is not None and not self._stop_child(process):
                raise RuntimeError("worker termination could not be proven") from exc
        except BaseException:
            # A failed ledger read, selector, or supervisor must not strand a
            # child outside the normal deadline loop. Preserve the executing
            # receipt for reconciliation; never turn unknown into success.
            if process is not None and not self._stop_child(process):
                self._fatal = "worker_stop_unproven_preserve_capacity"
            raise
        finally:
            if process is not None:
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                if process.stdout:
                    process.stdout.close()
        with self._lock:
            state = self.ledger.get(principal, row["id"])["state"]
            if state == "cancel_requested" or self._stop.is_set():
                if state == "executing":
                    self.cancel(principal, row["id"])
                return self.ledger.finish(principal, row["id"], "cancelled",
                                          reason="worker_exit_confirmed")
            if reason:
                return self.ledger.finish(principal, row["id"], "failed", reason=reason)
            try:
                answer = json.loads(output, object_pairs_hook=_unique_pairs)
                _check_tree(answer)
                report = answer["report"]
                sha = object_hash(report)
                expected = provenance(self.root, spec["submission"], manifest(self.root), "development")
                if (sha != answer["report_sha256"] or sha != answer["replay_sha256"]
                        or len(canonical_bytes(report)) > spec["resources"]["output_bytes"]
                        or report["provenance"] != expected or report["submission"] != spec["submission"]
                        or report["evidence_level"] != EVIDENCE
                        or answer["enforcement"]["network"] != "kernel_denied"
                        or self.ledger._identity() != (receipt["source_sha256"], receipt["manifest_sha256"])):
                    raise MeterError("worker evidence identity mismatch")
                name = f"{self.directory}/results/{row['tenant_id']}/{row['id']}.json"
                write_new(self.root, name, report)
                result = {"summary": report["summary"], "report_sha256": sha,
                          "replay_sha256": sha, "provenance": expected,
                          "enforcement": answer["enforcement"],
                          "cpu_seconds": answer["cpu_seconds"], "max_rss_kib": answer["max_rss_kib"],
                          "wall_seconds": time.monotonic() - began,
                          "replay_kind": "same_engine_not_independent_review",
                          "evidence_level": EVIDENCE}
            except (KeyError, TypeError, ValueError, OSError):
                return self.ledger.finish(principal, row["id"], "failed", reason="evidence_validation_failed")
            # A crash between artifact write and settlement leaves retained bytes
            # and an uncertain receipt. Never replay or manufacture a success.
            return self.ledger.finish(principal, row["id"], "settled", result=result, digest=sha)

    def run_one(self):
        if self._stop.is_set():
            return False
        if not self._runner.acquire(blocking=False):
            return False
        try:
            if self._stop.is_set():
                return False
            item = self._next()
            if not item:
                return False
            if not item.get("skipped"):
                self._execute(item)
            return True
        except Exception:
            self._fatal = "controller_failed_preserve_state"
            self.pause()
            raise
        finally:
            self._runner.release()

    def start(self):
        if self._thread is not None or self._stop.is_set():
            raise MeterError("controller already started or stopped")

        def loop():
            try:
                while not self._stop.is_set():
                    self._wake.clear()
                    while not self._stop.is_set() and self.run_one():
                        pass
                    self._wake.wait(0.25)
            except Exception:
                self._fatal = "controller_failed_preserve_state"

        self._thread = threading.Thread(target=loop, name="synthetic-job-controller", daemon=False)
        self._thread.start()

    def close(self):
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(15)
            if self._thread.is_alive():
                raise MeterError("controller still active; preserve its ledger lock")
        if not self._runner.acquire(timeout=15):
            raise MeterError("runner still active; preserve its ledger lock")
        try:
            self.ledger.close()
        finally:
            self._runner.release()
