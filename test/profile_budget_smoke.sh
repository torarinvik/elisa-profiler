#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

DETAIL_LIMIT=1
EVENT_TRACE_LIMIT=10
CAPTURE_BYTE_LIMIT=1024

"${ELISA_CLANG:-clang}" -std=c11 -O2 -fno-builtin -pthread -DELISA_PROFILE_TIMING=1 \
    "$ROOT/test/collector_path_loss_smoke.c" "$ROOT/scripts/profiler_runtime.c" \
    -o "$WORK/path-loss"
ELISA_PROFILE_MODE=functions ELISA_PROFILE_MAX_STACKS="$DETAIL_LIMIT" ELISA_PROFILE_FD=3 \
    "$WORK/path-loss" 3>"$WORK/path-loss.raw"
python3 - "$WORK/path-loss.raw" <<'PY'
import sys
META_STACK_DROPPED_INDEX = 14
EXPECTED_DROPPED_PATH_EVENTS = 2
records = [line.rstrip("\n").split("\t") for line in open(sys.argv[1])]
paths = [record for record in records if record[2] == "stack"]
assert len(paths) == 1, paths
assert paths[0][3:6] == ["root", "2", "2"], paths
metadata = next(record for record in records if record[2] == "meta")
assert int(metadata[META_STACK_DROPPED_INDEX]) == EXPECTED_DROPPED_PATH_EVENTS, metadata
functions = [record for record in records if record[2:4] == ["location", "3"]]
assert {record[4]: int(record[6]) for record in functions} == {"root": 3, "child": 1}
PY

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
