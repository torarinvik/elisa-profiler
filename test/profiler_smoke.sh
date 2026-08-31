#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/hot_loop.elisa" \
    --warmup 1 --repeat 2 --location-timing --format json --output "$WORK/report.json"
test -s "$WORK/report.json"
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/included_program.elisa" \
    --format json --output "$WORK/included-report.json"
test -s "$WORK/included-report.json"
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/signed_values.elisa" \
    --repeat 2 --format json --output "$WORK/signed-report.json"
test -s "$WORK/signed-report.json"

python3 - "$WORK/report.json" "$WORK/included-report.json" "$WORK/signed-report.json" "$ROOT/examples/included_program.elisa" "$ROOT/examples/included_helper.elisa" <<'PY'
import json
from pathlib import Path
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)

assert report["schema_version"] == 1
assert report["summary"]["events"] == 100
assert report["summary"]["dropped"] == 0
assert report["summary"]["statement_events"] + report["summary"]["value_events"] == 100
assert report["run"]["exit_code"] == 0
assert report["run"]["warmup_repetitions"] == 1
assert report["run"]["warmup_ms"] > 0
assert report["run"]["requested_repetitions"] == 2
assert report["run"]["completed_repetitions"] == 2
assert report["run"]["location_timing"] is True
assert max(location["max_interval_ns"] for location in report["locations"]) > 0
assert report["functions"][0]["function"] == "accumulate"
assert report["functions"][0]["locations"] == 10
assert report["functions"][0]["statement_events"] == 50
assert report["functions"][0]["value_events"] == 44
assert report["source_mapping"]["mode"] == "include-aware"
assert report["source_mapping"]["unmapped_locations"] == 0

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

included_source = Path(sys.argv[4]).resolve()
helper_source = Path(sys.argv[5]).resolve()
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

with open(sys.argv[3], encoding="utf-8") as stream:
    signed_report = json.load(stream)
signed_values = [
    location for location in signed_report["locations"]
    if location["kind"] == "value" and location["function"] == "main"
]
assert signed_values
assert all(location["signed"] is True for location in signed_values)
assert any(
    location["variable"] == "first"
    and location["count"] == 2
    and location["minimum"] == -7
    and location["maximum"] == -7
    and location["sum"] == -14
    and location["last"] == -7
    for location in signed_values
)
assert any(
    location["variable"] == "second"
    and location["count"] == 2
    and location["minimum"] == -7
    and location["maximum"] == -7
    and location["sum"] == -14
    and location["last"] == -7
    for location in signed_values
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
