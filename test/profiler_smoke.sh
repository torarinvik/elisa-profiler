#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/hot_loop.elisa" \
    --warmup 1 --repeat 2 --location-timing --recent-path --format json --output "$WORK/report.json"
test -s "$WORK/report.json"
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/hot_loop.elisa" \
    --repeat 2 --location-timing --format folded --output "$WORK/hot-loop.folded"
grep -Eq '^main(;accumulate)? [1-9][0-9]*$' "$WORK/hot-loop.folded"
grep -Eq '^main;accumulate [1-9][0-9]*$' "$WORK/hot-loop.folded"
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/hot_loop.elisa" \
    --repeat 2 --location-timing --timing-clock cpu --format json \
    --output "$WORK/cpu-timing-report.json"
python3 - "$WORK/cpu-timing-report.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    cpu_report = json.load(stream)

assert cpu_report["run"]["location_timing"] is True
assert cpu_report["run"]["timing_clock"] == "cpu"
assert cpu_report["run"]["execution_ms_mean"] > 0
assert any(function["inclusive_ns"] > 0 for function in cpu_report["functions"])
print("CPU timing smoke OK")
PY
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/hot_loop.elisa" \
    --repeat 2 --location-timing --format speedscope --output "$WORK/hot-loop.speedscope.json"
test -s "$WORK/hot-loop.speedscope.json"
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/hot_loop.elisa" \
    --repeat 2 --location-timing --format html --top 5 --output "$WORK/hot-loop.html"
test -s "$WORK/hot-loop.html"
grep -q '<table data-sortable>' "$WORK/hot-loop.html"
grep -q 'Call graph (top 1)' "$WORK/hot-loop.html"
grep -q 'main;accumulate' "$WORK/hot-loop.html"
grep -q 'Max stack depth' "$WORK/hot-loop.html"
grep -q 'Optimization' "$WORK/hot-loop.html"
grep -q 'Timing clock' "$WORK/hot-loop.html"
grep -q 'Compile' "$WORK/hot-loop.html"
grep -q 'Definition' "$WORK/hot-loop.html"
grep -q 'Measured repetitions' "$WORK/hot-loop.html"
grep -q 'run 2' "$WORK/hot-loop.html"
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/hot_loop.elisa" \
    --repeat 2 --location-timing --format text --output "$WORK/timing.txt"
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/hot_loop.elisa" \
    --opt-level 2 --repeat 2 --location-timing --format json --output "$WORK/o2-report.json"
"$ROOT/scripts/elisa-profiler" compare "$WORK/report.json" "$WORK/o2-report.json" \
    --format text --top 3 --output "$WORK/comparison.txt"
"$ROOT/scripts/elisa-profiler" compare "$WORK/report.json" "$WORK/o2-report.json" \
    --format json --output "$WORK/comparison.json"
"$ROOT/scripts/elisa-profiler" compare "$WORK/report.json" "$WORK/o2-report.json" \
    --format html --top 3 --output "$WORK/comparison.html"
test -s "$WORK/comparison.html"
grep -q 'Elisa profile comparison' "$WORK/comparison.html"
grep -q 'Source-location changes' "$WORK/comparison.html"
grep -q 'Call-edge changes' "$WORK/comparison.html"
grep -q 'Call-stack changes' "$WORK/comparison.html"
grep -q 'Dropped trace events' "$WORK/comparison.html"
grep -q 'DOMContentLoaded' "$WORK/comparison.html"
python3 - "$WORK/timing.txt" "$WORK/comparison.txt" "$WORK/o2-report.json" "$WORK/comparison.json" "$WORK/hot-loop.speedscope.json" <<'PY'
import json
import sys

text = open(sys.argv[1], encoding="utf-8").read()
comparison_text = open(sys.argv[2], encoding="utf-8").read()
assert text.index("main (calls=") < text.index("accumulate (calls=")
assert "stack-depth=2 stack-overflow=0" in text
assert "defined at hot_loop.elisa:9" in text
assert "Measured repetitions:" in text
assert "run 1: exit 0" in text
assert "run 2: exit 0" in text
assert "compile=" in text
assert "trace=" in text
assert "opt=-O0" in text
assert "timing-clock=wall" in text
assert "Elisa profile comparison" in comparison_text
assert "wall mean:" in comparison_text
assert "Source locations" in comparison_text
assert "Call-edge changes" in comparison_text
assert "Call-stack changes" in comparison_text
assert "dropped trace events:" in comparison_text
assert "stack overflow entries:" in comparison_text
o2_report = json.load(open(sys.argv[3], encoding="utf-8"))
assert o2_report["run"]["opt_level"] == "-O2"
comparison = json.load(open(sys.argv[4], encoding="utf-8"))
assert comparison["kind"] == "profile_comparison"
assert comparison["baseline"]["opt_level"] == "-O0"
assert comparison["candidate"]["opt_level"] == "-O2"
assert "execution_ms_mean" in comparison["metrics"]
assert "compile_ms" in comparison["metrics"]
assert comparison["functions"]
assert "locations" in comparison
assert "stacks" in comparison
assert comparison["stacks"]
assert comparison["metrics"]["dropped_events"]["baseline"] == 0
assert comparison["metrics"]["dropped_events"]["candidate"] == 0
assert comparison["metrics"]["stack_overflow_entries"]["baseline"] == 0
assert comparison["metrics"]["stack_overflow_entries"]["candidate"] == 0
assert comparison["warnings"] == []
speedscope = json.load(open(sys.argv[5], encoding="utf-8"))
assert speedscope["activeProfileIndex"] == 0
assert speedscope["shared"]["frames"]
assert speedscope["profiles"][0]["unit"] == "nanoseconds"
assert speedscope["profiles"][0]["samples"]
assert sum(speedscope["profiles"][0]["weights"]) > 0
PY
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/included_program.elisa" \
    --format json --output "$WORK/included-report.json"
test -s "$WORK/included-report.json"
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/signed_values.elisa" \
    --repeat 2 --format json --output "$WORK/signed-report.json"
test -s "$WORK/signed-report.json"
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/recursive.elisa" \
    --repeat 2 --location-timing --format json --output "$WORK/recursive-report.json"
test -s "$WORK/recursive-report.json"
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/deep_recursion.elisa" \
    --format json --output "$WORK/deep-recursion-report.json"
test -s "$WORK/deep-recursion-report.json"
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/threaded.elisa" \
    --repeat 2 --location-timing --format json --output "$WORK/threaded-report.json"
test -s "$WORK/threaded-report.json"
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/threaded.elisa" \
    --location-timing --timing-clock cpu --format json --output "$WORK/threaded-cpu-report.json"
test -s "$WORK/threaded-cpu-report.json"

python3 - "$WORK/report.json" "$WORK/included-report.json" "$WORK/signed-report.json" "$WORK/recursive-report.json" "$WORK/deep-recursion-report.json" "$ROOT/examples/included_program.elisa" "$ROOT/examples/included_helper.elisa" <<'PY'
import json
from pathlib import Path
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)

assert report["schema_version"] == 1
assert report["summary"]["events"] == 104
assert report["summary"]["dropped"] == 0
assert report["summary"]["max_stack_depth"] == 2
assert report["summary"]["stack_overflow_entries"] == 0
assert report["summary"]["thread_count"] == 1
assert (
    report["summary"]["statement_events"]
    + report["summary"]["value_events"]
    + report["summary"]["function_events"]
    == 104
)
assert report["summary"]["function_events"] == 4
assert report["run"]["exit_code"] == 0
assert report["run"]["warmup_repetitions"] == 1
assert report["run"]["warmup_ms"] > 0
assert report["run"]["requested_repetitions"] == 2
assert report["run"]["completed_repetitions"] == 2
assert report["run"]["successful_repetitions"] == 2
assert report["run"]["failed_repetitions"] == 0
assert report["run"]["measurement_repetitions"] == 2
assert report["run"]["measurement_basis"] == "successful"
assert report["run"]["location_timing"] is True
assert report["run"]["opt_level"] == "-O0"
assert report["recent_events"]
assert report["recent_events"][-1]["function"] == "main"
assert all(repetition["recent_events"] for repetition in report["run"]["repetitions"])
assert report["run"]["repetitions"][-1]["recent_events"] == report["recent_events"]
assert all(
    "compiler_line" in event
    and "source" in event
    and "source_text" in event
    for repetition in report["run"]["repetitions"]
    for event in repetition["recent_events"]
)
assert report["run"]["cpu_ms"] is not None
assert report["run"]["cpu_ms"] >= 0
assert all(repetition["cpu_ms"] is not None for repetition in report["run"]["repetitions"])
assert all(repetition["cpu_ms"] >= 0 for repetition in report["run"]["repetitions"])
assert all(repetition["trace_events"] > 0 for repetition in report["run"]["repetitions"])
assert all(repetition["trace_threads"] == 1 for repetition in report["run"]["repetitions"])
assert all(repetition["trace_dropped"] == 0 for repetition in report["run"]["repetitions"])
assert "peak_rss_bytes" in report["run"]
assert all("peak_rss_bytes" in repetition for repetition in report["run"]["repetitions"])
if sys.platform == "darwin":
    assert report["run"]["peak_rss_bytes"] > 0
    assert all(repetition["peak_rss_bytes"] > 0 for repetition in report["run"]["repetitions"])
assert max(location["max_interval_ns"] for location in report["locations"]) > 0
assert report["functions"][0]["function"] == "accumulate"
assert report["functions"][0]["interval_ns"] > 0
assert report["functions"][0]["max_interval_ns"] > 0
assert report["functions"][0]["locations"] == 11
assert report["functions"][0]["statement_events"] == 50
assert report["functions"][0]["value_events"] == 44
assert report["functions"][0]["call_events"] == 2
assert report["functions"][0]["completed_calls"] == 2
assert report["functions"][0]["inclusive_ns"] > 0
assert report["functions"][0]["inclusive_ns"] >= report["functions"][0]["self_ns"]
assert report["functions"][0]["mean_inclusive_ns"] == report["functions"][0]["inclusive_ns"] // 2
assert report["functions"][0]["inclusive_percent"] > 0
assert report["functions"][0]["events"] == 96
main_function = next(function for function in report["functions"] if function["function"] == "main")
assert main_function["completed_calls"] == main_function["call_events"] == 2
assert main_function["inclusive_ns"] > 0
assert main_function["inclusive_ns"] >= main_function["self_ns"]
assert main_function["mean_inclusive_ns"] == main_function["inclusive_ns"] // 2
assert abs(main_function["inclusive_percent"] - 100.0) < 1e-9
assert main_function["inclusive_ns"] >= report["functions"][0]["inclusive_ns"]
assert len(report["call_edges"]) == 1
hot_edge = report["call_edges"][0]
assert hot_edge["caller"] == "main"
assert hot_edge["callee"] == "accumulate"
assert hot_edge["call_events"] == hot_edge["completed_calls"] == 2
assert hot_edge["inclusive_ns"] == report["functions"][0]["inclusive_ns"]
stacks = {stack["stack"]: stack for stack in report["stacks"]}
assert stacks["main"]["call_events"] == stacks["main"]["completed_calls"] == 2
assert stacks["main"]["self_ns"] > 0
assert stacks["main;accumulate"]["call_events"] == stacks["main;accumulate"]["completed_calls"] == 2
assert stacks["main;accumulate"]["self_ns"] > 0
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

with open(sys.argv[4], encoding="utf-8") as stream:
    recursive_report = json.load(stream)
with open(sys.argv[5], encoding="utf-8") as stream:
    deep_report = json.load(stream)
recursive_functions = {
    function["function"]: function for function in recursive_report["functions"]
}
assert recursive_functions["countdown"]["call_events"] == 14
assert recursive_functions["countdown"]["completed_calls"] == 14
assert next(
    edge
    for edge in recursive_report["call_edges"]
    if edge["caller"] == "countdown" and edge["callee"] == "countdown"
)["call_events"] == 12
assert max(stack["stack"].count("countdown") for stack in recursive_report["stacks"]) == 7
assert deep_report["summary"]["max_stack_depth"] == 1024
assert deep_report["summary"]["stack_overflow_entries"] > 0
assert deep_report["summary"]["dropped"] == 0

included_source = Path(sys.argv[6]).resolve()
helper_source = Path(sys.argv[7]).resolve()
with open(sys.argv[2], encoding="utf-8") as stream:
    included_report = json.load(stream)
helper_locations = [
    location for location in included_report["locations"]
    if location["function"] == "included_work"
]
assert helper_locations
assert any(
    location["kind"] == "function"
    and location["line"] == 1
    and location["count"] == 1
    and Path(location["source"]) == helper_source
    for location in helper_locations
)
included_function = next(
    function for function in included_report["functions"]
    if function["function"] == "included_work"
)
assert included_function["definitions"] == [
    {
        "source": str(helper_source),
        "line": 1,
        "compiler_line": 1,
        "source_text": "def included_work(limit: i64) -> i64:",
    }
]
included_edge = next(
    edge
    for edge in included_report["call_edges"]
    if edge["caller"] == "main" and edge["callee"] == "included_work"
)
assert included_edge["call_events"] == included_edge["completed_calls"] == 1
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
signed_main = next(function for function in signed_report["functions"] if function["function"] == "main")
assert signed_main["completed_calls"] == signed_main["call_events"] == 2
assert signed_main["inclusive_ns"] == 0
assert signed_main["self_ns"] == 0
assert signed_main["mean_inclusive_ns"] == 0
assert signed_main["inclusive_percent"] == 0.0
signed_stack = next(stack for stack in signed_report["stacks"] if stack["stack"] == "main")
assert signed_stack["call_events"] == signed_stack["completed_calls"] == 2
assert signed_stack["self_ns"] == 0
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

python3 - "$WORK/threaded-report.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)

assert report["run"]["exit_code"] == 0
assert report["run"]["completed_repetitions"] == 2
assert report["summary"]["dropped"] == 0
assert report["summary"]["max_stack_depth"] == 1
assert report["summary"]["thread_count"] >= 3
worker = next(function for function in report["functions"] if function["function"] == "worker")
assert worker["call_events"] == worker["completed_calls"] == 4
assert worker["inclusive_ns"] > 0
assert any(location["function"] == "worker" for location in report["locations"])
worker_tail = next(
    location for location in report["locations"]
    if location["function"] == "worker" and "usleep" in (location.get("source_text") or "")
)
assert worker_tail["max_interval_ns"] >= 1_000_000
return_location = next(
    location for location in report["locations"]
    if location["function"] == "worker" and "return null" in (location.get("source_text") or "")
)
assert return_location["max_interval_ns"] < 1_000_000
print("threaded profiling OK")
PY

python3 - "$WORK/threaded-cpu-report.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)

assert report["run"]["location_timing"] is True
assert report["run"]["timing_clock"] == "cpu"
worker = next(function for function in report["functions"] if function["function"] == "worker")
assert worker["inclusive_ns"] > 0
worker_tail = next(
    location for location in report["locations"]
    if location["function"] == "worker" and "usleep" in (location.get("source_text") or "")
)
assert worker_tail["max_interval_ns"] < 1_000_000
return_location = next(
    location for location in report["locations"]
    if location["function"] == "worker" and "return null" in (location.get("source_text") or "")
)
assert return_location["max_interval_ns"] < 1_000_000
print("threaded CPU timing OK")
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
assert report["run"]["successful_repetitions"] == 0
assert report["run"]["failed_repetitions"] == 1
assert report["run"]["measurement_repetitions"] == 1
assert report["run"]["measurement_basis"] == "all_completed"
assert report["summary"]["events"] >= 1
assert report["locations"][-1]["line"] == 2
assert report["recent_events"]
assert report["recent_events"][-1]["function"] == "main"
assert report["recent_events"][-1]["line"] == 2
assert report["active_stack"] == {
    "tracked_depth": 1,
    "overflow_depth": 0,
    "stack": ["main"],
}
crash_main = next(function for function in report["functions"] if function["function"] == "main")
assert crash_main["call_events"] == 1
assert crash_main["completed_calls"] == 0
crash_stack = next(stack for stack in report["stacks"] if stack["stack"] == "main")
assert crash_stack["call_events"] == 1
assert crash_stack["completed_calls"] == 0
print("crash capture OK")
PY

set +e
"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/timeout.elisa" --timeout 2 --format json --output "$WORK/timeout-report.json"
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
assert report["run"]["successful_repetitions"] == 0
assert report["run"]["failed_repetitions"] == 1
assert report["run"]["measurement_repetitions"] == 1
assert report["run"]["measurement_basis"] == "all_completed"
assert report["run"]["repetitions"][0]["timed_out"] is True
assert report["run"]["timeout_s"] == 2.0
assert "peak_rss_bytes" in report["run"]
assert "peak_rss_bytes" in report["run"]["repetitions"][0]
assert report["active_stack"] == {
    "tracked_depth": 1,
    "overflow_depth": 0,
    "stack": ["main"],
}
print("timeout capture OK")
PY

python3 "$ROOT/test/profile_schema_smoke.py" "$ROOT/docs/profile.schema.json" \
    "$WORK/report.json" "$WORK/cpu-timing-report.json" "$WORK/included-report.json" "$WORK/signed-report.json" \
    "$WORK/recursive-report.json" "$WORK/deep-recursion-report.json" \
    "$WORK/threaded-cpu-report.json" "$WORK/crash-report.json" "$WORK/timeout-report.json"
python3 "$ROOT/test/profile_schema_smoke.py" "$ROOT/docs/profile-comparison.schema.json" \
    "$WORK/comparison.json"
