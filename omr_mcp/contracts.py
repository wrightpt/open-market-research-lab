"""Sanitized public tool schemas agreed through backend contract review."""

DATASET = {"type": "string", "minLength": 1,
           "description": "Dataset identifier; backend decides access.",
           "examples": ["synthetic-perp-daily-v1"]}
EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}
DESCRIBE = {"type": "object", "properties": {"dataset": DATASET},
            "required": ["dataset"], "additionalProperties": False}
QUERY = {
    "type": "object",
    "properties": {
        "dataset": DATASET,
        "asset": {"type": "string", "minLength": 1,
                  "description": "Series identifier; BTC/ETH/HYPE/XMR examples are invented fixture series.",
                  "examples": ["BTC", "ETH", "HYPE", "XMR"]},
        "start": {"type": "string", "format": "date-time", "description": "Inclusive UTC bucket boundary."},
        "end": {"type": "string", "format": "date-time", "description": "Exclusive UTC bucket boundary."},
        "max_rows": {"type": "integer", "minimum": 1, "maximum": 500},
    },
    "required": ["dataset", "asset", "start", "end", "max_rows"],
    "additionalProperties": False,
}
INPUT_SCHEMAS = {
    "list_datasets": EMPTY, "describe_dataset": DESCRIBE, "get_coverage": DESCRIBE,
    "get_schema": DESCRIBE, "query_timeseries": QUERY,
    "get_research_examples": EMPTY, "get_usage_limits": EMPTY,
}
