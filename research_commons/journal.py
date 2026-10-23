"""Single-writer, durable local evidence journal. Not hostile-owner custody."""

import fcntl
import os
import re
import threading
from datetime import datetime, timezone

from market_lab.io import LabError, canonical_bytes, load_json, object_hash, repo_path

MAX_EVENT_BYTES = 2_000_000
MAX_EVENTS = 1000
MAX_TOTAL_BYTES = 128 * 1024 * 1024
KEY = re.compile(r"[A-Za-z0-9_-]{8,100}\Z")


class Journal:
    def __init__(self, root, directory="artifacts/commons"):
        self.path = repo_path(root, f"{directory}/events", output=True)
        self.path.mkdir(parents=True, exist_ok=True)
        lock_path = repo_path(root, f"{directory}/writer.lock", output=True)
        self._lock_file = lock_path.open("a+b")
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._lock_file.close()
            raise LabError("this journal already has an active writer") from exc
        self.lock = threading.RLock()
        self.events = []
        self.total_bytes = 0
        try:
            self._read()
        except Exception:
            self.close()
            raise

    def _read(self):
        paths = sorted(self.path.glob("*.json"))
        if len(paths) > MAX_EVENTS:
            raise LabError("journal event limit exceeded")
        previous = "0" * 64
        for number, path in enumerate(paths, 1):
            if path.is_symlink() or path.name != f"{number:06d}.json":
                raise LabError("journal sequence is invalid")
            self.total_bytes += path.stat().st_size
            if self.total_bytes > MAX_TOTAL_BYTES:
                raise LabError("journal storage limit exceeded")
            event = load_json(path, MAX_EVENT_BYTES)
            if not isinstance(event, dict):
                raise LabError("invalid journal event")
            body = {key: value for key, value in event.items() if key != "sha256"}
            if (event.get("seq") != number or event.get("previous_sha256") != previous
                    or event.get("sha256") != object_hash(body)):
                raise LabError("journal hash verification failed; preserve files for review")
            previous = event["sha256"]
            self.events.append(event)

    def receipt(self, actor, key, fingerprint):
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise LabError("Idempotency-Key must contain 8–100 letters, digits, '-' or '_'")
        matches = [e for e in self.events if e["actor"] == actor and e["request_id"] == key]
        if not matches:
            return None
        if any(e["request_sha256"] != fingerprint for e in matches):
            raise LabError("idempotency key was already used for different input")
        return matches[-1]

    def append(self, actor, kind, study_id, key, fingerprint, payload):
        with self.lock:
            seq = len(self.events) + 1
            if seq > MAX_EVENTS:
                raise LabError("local journal is full; preserve it and start a new workspace")
            event = {
                "schema_version": 1, "seq": seq, "actor": actor, "kind": kind,
                "study_id": study_id, "request_id": key, "request_sha256": fingerprint,
                "at": datetime.now(timezone.utc).isoformat(), "payload": payload,
                "previous_sha256": self.events[-1]["sha256"] if self.events else "0" * 64,
            }
            event["sha256"] = object_hash(event)
            data = canonical_bytes(event)
            if len(data) > MAX_EVENT_BYTES or self.total_bytes + len(data) > MAX_TOTAL_BYTES:
                raise LabError("local evidence storage limit exceeded")
            target = self.path / f"{seq:06d}.json"
            temporary = self.path / f".{seq:06d}-{os.getpid()}.pending"
            try:
                with temporary.open("xb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                # Hard-link installs the complete file without overwriting evidence.
                os.link(temporary, target)
                descriptor = os.open(self.path, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            except OSError as exc:
                raise LabError("journal write failed; restart to reconcile retained evidence") from exc
            finally:
                if temporary.exists():
                    temporary.unlink()
            self.events.append(event)
            self.total_bytes += len(data)
            return event

    def close(self):
        if not self._lock_file.closed:
            fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            self._lock_file.close()
