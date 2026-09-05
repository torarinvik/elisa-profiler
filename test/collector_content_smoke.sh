#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d "${ELISA_TEST_TMPDIR:-/tmp}/elisa-profiler-collector.XXXXXX")"
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
ELISA_PROFILE_FRAMED=1 "$WORK/collector" 2>"$WORK/framed-profile.txt"
framed_exit_status=$?
set -e
test "$exit_status" -eq 0
test "$timing_exit_status" -eq 0
test "$framed_exit_status" -eq 0

python3 - "$WORK/profile.txt" "$WORK/timing-profile.txt" "$WORK/framed-profile.txt" <<'PY'
import sys
MASK = (1 << 64) - 1

def read_lines(path: str, framed: bool = False):
    result = []
    expected_sequence = 0
    for raw_line in open(path, encoding="utf-8"):
        line = raw_line.rstrip("\n")
        if framed:
            parts = line.split("\t", 6)
            assert parts[:3] == ["ELISA_PROFILE", "1", "frame"], parts
            assert int(parts[3]) == expected_sequence, (parts[3], expected_sequence)
            expected_sequence += 1
            length = int(parts[4])
            checksum = int(parts[5])
            payload = parts[6].encode()
            assert len(payload) == length, (len(payload), length)
            actual = 14695981039346656037
            for byte in payload:
                actual = ((actual ^ byte) * 1099511628211) & MASK
            assert actual == checksum, (actual, checksum)
            result.append(payload.decode())
        else:
            result.append(line)
    return result

def check_report(path: str, framed: bool = False) -> None:
    lines = [line.split("\t") for line in read_lines(path, framed) if line.startswith("ELISA_PROFILE\t")]
    assert [line[2] for line in lines if line[2] in ("begin", "end")] == ["begin", "end"]
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
check_report(sys.argv[3], framed=True)
print("collector content smoke OK")
PY
