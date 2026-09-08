#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

DETAIL_LIMIT=1
EVENT_TRACE_LIMIT=10
CAPTURE_BYTE_LIMIT=1024

ELISA_PROFILE_MAX_LOCATIONS="$DETAIL_LIMIT" \
ELISA_PROFILE_MAX_CALL_EDGES="$DETAIL_LIMIT" \
ELISA_PROFILE_MAX_STACKS="$DETAIL_LIMIT" \
    "$ROOT/bin/elisa-profiler" profile "$ROOT/examples/hot_loop.elisa" \
    --format json --event-trace --max-event-trace-events "$EVENT_TRACE_LIMIT" \
    --max-capture-bytes "$CAPTURE_BYTE_LIMIT" \
    --output "$WORK/report.json"

python3 "$ROOT/test/profile_schema_smoke.py" \
    "$ROOT/docs/profile.schema.json" "$WORK/report.json"

python3 - "$WORK/report.json" "$DETAIL_LIMIT" "$EVENT_TRACE_LIMIT" "$CAPTURE_BYTE_LIMIT" <<'PY'
import json
import sys

report_path, detail_limit_text, event_trace_limit_text, capture_byte_limit_text = sys.argv[1:]
detail_limit = int(detail_limit_text)
event_trace_limit = int(event_trace_limit_text)
capture_byte_limit = int(capture_byte_limit_text)
report = json.load(open(report_path, encoding="utf-8"))
summary = report["summary"]
repetition = report["run"]["repetitions"][0]

assert summary["location_limit"] == detail_limit
assert summary["call_edge_limit"] == detail_limit
assert summary["stack_limit"] == detail_limit
assert summary["capture_byte_limit"] == capture_byte_limit
assert summary["capture_bytes_dropped"] > 0
assert summary["detail_budget_exceeded"] is True
assert summary["dropped"] > 0 or summary["dropped_call_edges"] > 0 or summary["dropped_stacks"] > 0
assert repetition["detail_budget_exceeded"] is True
assert repetition["location_limit"] == detail_limit
assert repetition["call_edge_limit"] == detail_limit
assert repetition["stack_limit"] == detail_limit
assert repetition["capture_byte_limit"] == capture_byte_limit
assert repetition["capture_bytes_dropped"] > 0
assert repetition["trace_event_limit"] == event_trace_limit
assert repetition["trace_events_captured"] <= event_trace_limit
assert repetition["trace_events"] == summary["events"]
assert len(repetition["event_trace"]) == repetition["trace_events_captured"]
assert all("thread_id" in event and "timestamp_ns" in event for event in repetition["event_trace"])
assert all(isinstance(event["thread_id"], int) and event["thread_id"] >= 0 for event in repetition["event_trace"])
assert all(isinstance(event["timestamp_ns"], int) and event["timestamp_ns"] >= 0 for event in repetition["event_trace"])
print("profile budget smoke OK")
PY
