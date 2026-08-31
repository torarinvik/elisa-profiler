#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/hot_loop.elisa" \
    --warmup 1 --repeat 2 --format json --output "$WORK/report.json"
test -s "$WORK/report.json"
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/included_program.elisa" \
    --format json --output "$WORK/included-report.json"
test -s "$WORK/included-report.json"

python3 - "$WORK/report.json" "$WORK/included-report.json" "$ROOT/examples/included_program.elisa" "$ROOT/examples/included_helper.elisa" <<'PY'
import json
from pathlib import Path
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)

assert report["schema_version"] == 1
assert report["summary"]["events"] == 100
assert report["summary"]["dropped"] == 0
assert report["run"]["exit_code"] == 0
assert report["run"]["warmup_repetitions"] == 1
assert report["run"]["warmup_ms"] > 0
assert report["run"]["requested_repetitions"] == 2
assert report["run"]["completed_repetitions"] == 2
assert report["functions"][0]["function"] == "accumulate"

hot_total = next(
    location["count"]
    for location in report["locations"]
    if location["function"] == "accumulate"
    and location["line"] == 5
    and location["kind"] == "value"
    and location["variable"] == "total"
)
assert hot_total == 20
assert next(
    location["maximum"]
    for location in report["locations"]
    if location["function"] == "accumulate"
    and location["line"] == 5
    and location["kind"] == "value"
    and location["variable"] == "total"
) == 45
assert next(
    location["sum"]
    for location in report["locations"]
    if location["function"] == "accumulate"
    and location["line"] == 5
    and location["kind"] == "value"
    and location["variable"] == "total"
) == 330

included_source = Path(sys.argv[3]).resolve()
helper_source = Path(sys.argv[4]).resolve()
with open(sys.argv[2], encoding="utf-8") as stream:
    included_report = json.load(stream)
helper_locations = [
    location for location in included_report["locations"]
    if location["function"] == "included_work"
]
assert helper_locations
assert all(Path(location["source"]) == helper_source for location in helper_locations)
assert any(
    location["line"] == 5
    and location["kind"] == "value"
    and location["variable"] == "result"
    and location["count"] == 10
    for location in helper_locations
)
assert any(
    location["function"] == "main"
    and Path(location["source"]) == included_source
    for location in included_report["locations"]
)

print("profiler smoke OK")
PY

set +e
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/crash.elisa" \
    --format json --output "$WORK/crash-report.json"
crash_status=$?
set -e
test "$crash_status" -eq 134

python3 - "$WORK/crash-report.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)

assert report["run"]["exit_code"] is None
assert report["run"]["signal"] == 6
assert report["summary"]["events"] >= 1
assert report["locations"][-1]["line"] == 2
print("crash capture OK")
PY

set +e
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/timeout.elisa" --timeout 0.1 --format json --output "$WORK/timeout-report.json"
timeout_status=$?
set -e
test "$timeout_status" -eq 143

python3 - "$WORK/timeout-report.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)

assert report["run"]["exit_code"] is None
assert report["run"]["signal"] == 15
assert report["run"]["repetitions"][0]["timed_out"] is True
assert report["run"]["timeout_s"] == 0.1
print("timeout capture OK")
PY
