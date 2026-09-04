#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

CC="${ELISA_CLANG:-clang}"
"$CC" -std=c11 -O2 -fno-builtin -pthread -DELISA_PROFILE_TIMING=1 \
    -o "$WORK/timing-mismatch" \
    "$ROOT/scripts/profiler_runtime.c" "$ROOT/test/timing_mismatch_smoke.c"

"$WORK/timing-mismatch" 2>"$WORK/profile.txt"
python3 - "$WORK/profile.txt" <<'PY'
import sys

records = [
    line.rstrip("\n").split("\t")
    for line in open(sys.argv[1], encoding="utf-8")
    if line.startswith("ELISA_PROFILE\t")
]
locations = [record for record in records if record[2] == "location"]
statement = {int(record[5]): record for record in locations if record[3] == "1"}
assert 2 in statement and 4 in statement
# The 20 ms delay occurs after the foreign exit. It must not be charged to
# the location immediately preceding that exit.
assert int(statement[2][14]) < 10_000_000, statement[2]
assert statement[4][13:] == ["0", "0"], statement[4]
function = next(record for record in locations if record[3] == "3")
assert function[11] == "0", function
print("timing mismatch smoke OK")
PY
