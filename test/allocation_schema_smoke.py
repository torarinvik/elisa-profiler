#!/usr/bin/env python3
"""Keep legacy and attributed allocation records closed and compatible."""
import json
from pathlib import Path

from profile_schema_smoke import SchemaError, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "docs/profile.schema.json").read_text(encoding="utf-8"))
EVENT_SCHEMA = SCHEMA["$defs"]["allocation_event"]
LEGACY = {
    "kind": "alloc", "kind_code": 1, "address": 1, "size_bytes": 8,
    "old_address": 0, "old_size_bytes": 0, "arena": 1, "region": 0,
    "sequence": 0, "thread_id": 1, "timestamp_ns": 1, "repetition": 1,
}
SITE = {
    "site_known": 1, "site_function_id": 2**64 - 1, "site_line": 10,
    "site_caller_id": 1, "site_caller_line": 2, "site_stack_omitted": 0,
    "site_stack": "1:2;18446744073709551615:10",
}


def check(event):
    validate(event, EVENT_SCHEMA, SCHEMA, "allocation")


def reject(event):
    try:
        check(event)
    except SchemaError:
        return
    raise AssertionError(f"accepted malformed allocation: {event}")


check(LEGACY)
check(LEGACY | SITE)
check(LEGACY | SITE | {"site_known": 0, "site_stack": "-"})
for field in SITE:
    partial = LEGACY | SITE
    del partial[field]
    reject(partial)
    reject(LEGACY | {field: SITE[field]})
for field, value in (
    ("site_known", 2), ("site_function_id", 2**64), ("site_line", -1),
    ("site_caller_id", True), ("site_stack", ""), ("site_stack", "1:2;"),
    ("site_stack", ";".join(["1:2"] * 9)), ("unrecognized", 1),
):
    reject(LEGACY | SITE | {field: value})
print("allocation schema smoke OK: legacy, full attribution, and malformed controls")
