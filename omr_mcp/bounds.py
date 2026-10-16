"""Small strict JSON boundary shared by transport and protocol."""

import json
import math

MAX_LINE = 65_536
MAX_REQUEST = 32_768
MAX_RESPONSE = 262_144
MAX_OUTPUT = 2_097_152


def validate(value, depth=0, max_depth=16):
    if depth > max_depth:
        raise ValueError("JSON nesting limit")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Nonfinite number")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("Invalid object key")
            key.encode("utf-8")
            validate(child, depth + 1, max_depth)
    elif isinstance(value, list):
        for child in value:
            validate(child, depth + 1, max_depth)
    elif isinstance(value, str):
        value.encode("utf-8")  # Reject lone escaped surrogates, not just raw bad UTF-8.
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError("Invalid JSON value")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def encode(value, limit, max_depth=16):
    validate(value, max_depth=max_depth)
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(data) > limit:
        raise ValueError("JSON byte limit")
    return data


def decode(data, limit):
    if len(data) > limit:
        raise ValueError("JSON byte limit")
    value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs)
    validate(value)
    return value
