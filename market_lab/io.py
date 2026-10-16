"""Bounded local JSON and artifact I/O; this is not an OS sandbox."""

import hashlib
import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_JSON_BYTES = 32_768


class LabError(ValueError):
    """An expected, user-actionable validation failure."""


def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def object_hash(value):
    return digest(canonical_bytes(value))


def repo_path(root, name, *, output=False):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise LabError("use a repository-relative path without '..'")
    if output and (path.parts[0] != "artifacts" or len(path.parts) < 2):
        raise LabError("outputs must be files under artifacts/")
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise LabError("symlink paths are not allowed")
    if not current.resolve().is_relative_to(root.resolve()):
        raise LabError("path escapes repository")
    return current


def read_bytes(path, limit):
    if not path.is_file():
        raise LabError("input must be an existing regular file")
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise LabError(f"input exceeds {limit} bytes")
    return data


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LabError("duplicate JSON keys are not allowed")
        result[key] = value
    return result


def _check_tree(value, depth=0):
    if depth > 16:
        raise LabError("JSON nesting exceeds 16 levels")
    if isinstance(value, float) and not math.isfinite(value):
        raise LabError("JSON numbers must be finite")
    children = value.values() if isinstance(value, dict) else value
    if isinstance(value, (dict, list)):
        for child in children:
            _check_tree(child, depth + 1)


def load_json(path, limit=MAX_JSON_BYTES):
    try:
        value = json.loads(read_bytes(path, limit), object_pairs_hook=_unique_pairs)
        _check_tree(value)
        return value
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, LabError):
            raise
        raise LabError("invalid or excessively nested JSON") from exc


def write_new(root, name, value):
    path = repo_path(root, name, output=True)
    payload = canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise LabError("artifact already exists; choose a new name, preserve evidence") from exc
    # Persist the directory entry before a holdout consumer can proceed.
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return path


def source_hash(root):
    """Bind executable code and contract, independent of checkout location."""
    paths = sorted(p.relative_to(root).as_posix() for p in (root / "market_lab").glob("*.py"))
    paths.append("schemas/submission.schema.json")
    entries = {name: digest(read_bytes(repo_path(root, name), 256_000)) for name in paths}
    return object_hash(entries)
