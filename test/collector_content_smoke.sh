#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

CC="${ELISA_CLANG:-clang}"
"$CC" -std=c11 -O2 -fno-builtin -pthread \
    -o "$WORK/collector" \
    "$ROOT/scripts/profiler_runtime.c" \
    "$ROOT/test/collector_content_smoke.c"
"$CC" -std=c11 -O2 -fno-builtin -pthread -DELISA_PROFILE_TIMING=1 \
    -o "$WORK/collector-timing" \
    "$ROOT/scripts/profiler_runtime.c" \
    "$ROOT/test/collector_content_smoke.c"

set +e
"$WORK/collector" 2>"$WORK/profile.txt"
exit_status=$?
"$WORK/collector-timing" 2>"$WORK/timing-profile.txt"
timing_exit_status=$?
set -e
test "$exit_status" -eq 0
test "$timing_exit_status" -eq 0

python3 - "$WORK/profile.txt" "$WORK/timing-profile.txt" <<'PY'
import sys

def check_report(path: str) -> None:
    lines = [
        line.rstrip("\n").split("\t")
        for line in open(path, encoding="utf-8")
        if line.startswith("ELISA_PROFILE\t")
    ]
    locations = [line for line in lines if line[2] == "location"]
    function_locations = [line for line in locations if line[3] == "3"]
    statement_locations = [line for line in locations if line[3] == "1"]
    assert len(statement_locations) == 1
    assert statement_locations[0][4] == "main"
    assert statement_locations[0][5] == "2"
    assert statement_locations[0][6] == "2"
    value_locations = [line for line in locations if line[3] == "2"]
    assert len(value_locations) == 1
    assert value_locations[0][4:8] == ["main", "4", "2", "value"]
    assert value_locations[0][12] == "2"
    assert len(function_locations) == 2
    assert all(location[6] == "1" for location in function_locations)
    assert all(location[11] == "1" for location in function_locations)

    edges = [line for line in lines if line[2] == "call"]
    assert len(edges) == 1
    assert edges[0][3:7] == ["main", "worker", "1", "1"]

check_report(sys.argv[1])
check_report(sys.argv[2])
print("collector content smoke OK")
PY
