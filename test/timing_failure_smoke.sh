#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

CC="${ELISA_CLANG:-clang}"
"$CC" -std=c11 -O2 -fno-builtin -pthread \
    -DELISA_PROFILE_TIMING=1 -DELISA_PROFILE_CPU_TIMING=1 \
    -o "$WORK/timing-failure" \
    "$ROOT/scripts/profiler_runtime.c" "$ROOT/test/timing_failure_smoke.c"

"$WORK/timing-failure" 2>"$WORK/profile.txt"
python3 - "$WORK/profile.txt" <<'PY'
import sys

records = [
    line.rstrip("\n").split("\t")
    for line in open(sys.argv[1], encoding="utf-8")
    if line.startswith("ELISA_PROFILE\t")
]
locations = [record for record in records if record[2] == "location"]
function = next(record for record in locations if record[3] == "3")
assert function[9:12] == ["0", "0", "1"]
statement = next(record for record in locations if record[3] == "1")
assert statement[-2:] == ["0", "0"]
print("timing failure smoke OK")
PY
