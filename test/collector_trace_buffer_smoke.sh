#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d "${ELISA_TEST_TMPDIR:-/tmp}/elisa-profiler-trace-buffer.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

CC="${ELISA_CLANG:-clang}"
"$CC" -std=c11 -O2 -fno-builtin -pthread \
    -o "$WORK/collector" \
    "$ROOT/scripts/profiler_runtime.c" \
    "$ROOT/test/collector_trace_buffer_smoke.c"

ELISA_PROFILE_EVENT_TRACE=1 ELISA_PROFILE_THREAD_RECORDS=1 \
    "$WORK/collector" 2>"$WORK/profile.txt"

python3 - "$WORK/profile.txt" <<'PY'
import sys

lines = [
    line.rstrip("\n").split("\t")
    for line in open(sys.argv[1], encoding="utf-8")
    if line.startswith("ELISA_PROFILE\t")
]
paths = [line for line in lines if line[2] == "path"]
assert [int(line[3]) for line in paths] == [0, 1, 2], paths
assert [line[5] for line in paths] == ["trace-main", "trace-worker", "trace-worker"], paths
assert [line[4] for line in paths] == ["3", "3", "1"], paths
assert all(len(line) == 13 for line in paths), paths
assert [line[10] for line in paths] == ["0", "0", "0"], paths
assert [line[11] for line in paths] == ["0", "1", "1"], paths
timestamps = [int(line[12]) for line in paths]
assert all(timestamp >= 0 for timestamp in timestamps), timestamps
assert timestamps == sorted(timestamps), timestamps

threads = [line for line in lines if line[2] == "thread"]
assert len(threads) == 2, threads
assert any(line[12] == "1" and line[13] != "-" for line in threads), threads
assert any(line[12] == "0" and line[13] == "-" for line in threads), threads
print("collector trace buffer smoke OK")
PY
