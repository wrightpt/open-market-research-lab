"""Strict validation of the small JSON Schema subset used by this project."""

import math
import re

from .data import manifest
from .io import LabError, load_json, object_hash, repo_path

KEYWORDS = {
    "$schema", "title", "description", "type", "const", "properties", "required",
    "additionalProperties", "minimum", "maximum", "minLength", "maxLength", "pattern",
}


def validate_schema(value, schema, path="submission"):
    unsupported = set(schema) - KEYWORDS
    if unsupported:
        raise LabError("contract contains unsupported schema keywords")
    kind = schema.get("type")
    checks = {
        "object": lambda v: type(v) is dict,
        "string": lambda v: type(v) is str,
        "integer": lambda v: type(v) is int,
        "number": lambda v: type(v) is int or (type(v) is float and math.isfinite(v)),
        "boolean": lambda v: type(v) is bool,
    }
    if kind not in checks or not checks[kind](value):
        raise LabError(f"{path}: expected {kind}")
    if "const" in schema and object_hash(value) != object_hash(schema["const"]):
        raise LabError(f"{path}: value must match the contract constant")
    if kind == "object":
        properties = schema.get("properties", {})
        if set(schema.get("required", [])) - set(value):
            raise LabError(f"{path}: required field missing")
        if schema.get("additionalProperties") is not False:
            raise LabError("contract objects must reject additional properties")
        if set(value) - set(properties):
            raise LabError(f"{path}: unknown field")
        for key, child in value.items():
            validate_schema(child, properties[key], f"{path}.{key}")
    if kind in ("integer", "number"):
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise LabError(f"{path}: number outside allowed bounds")
    if kind == "string":
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", math.inf):
            raise LabError(f"{path}: string outside allowed length")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise LabError(f"{path}: string does not match required pattern")


def validate_submission(root, submission):
    schema = load_json(repo_path(root, "schemas/submission.schema.json"))
    validate_schema(submission, schema)
    metadata = manifest(root)
    for split in ("development", "holdout"):
        if submission["dataset"][f"{split}_sha256"] != metadata["splits"][split]["sha256"]:
            raise LabError(f"submission {split} hash does not match dataset identity")
    return submission


def load_submission(root, name):
    return validate_submission(root, load_json(repo_path(root, name)))
