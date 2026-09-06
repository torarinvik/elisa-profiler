#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d "${ELISA_TEST_TMPDIR:-/tmp}/elisa-profiler-identity.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

CC="${ELISA_CLANG:-clang}"
"$CC" -std=c11 -O2 -fno-builtin -pthread \
    -o "$WORK/collector" \
    "$ROOT/scripts/profiler_runtime.c" \
    "$ROOT/test/collector_identity_smoke.c"

ELISA_PROFILE_RECENT_PATH=1 "$WORK/collector" 2>"$WORK/profile.txt"

python3 - "$WORK/profile.txt" <<'PY'
import sys

path = sys.argv[1]
lines = [line.rstrip("\n").split("\t") for line in open(path, encoding="utf-8")]
records = [line for line in lines if len(line) >= 3 and line[:3] == ["ELISA_PROFILE", "1", "location"]]
assert any(line[3:8] == ["3", "identified_main", "10", "1", "-"] and line[-1] == "1001" for line in records), records
assert any(line[3:8] == ["3", "identified_worker", "20", "1", "-"] and line[-1] == "1004" for line in records), records
assert any(line[3:8] == ["1", "identified_main", "12", "1", "-"] and line[-1] == "1002" for line in records), records
assert any(line[3:8] == ["2", "identified_main", "13", "1", "counter"] and line[-1] == "1003" for line in records), records

edges = [line for line in lines if len(line) >= 3 and line[:3] == ["ELISA_PROFILE", "1", "call"]]
assert any(line[3:7] == ["identified_main", "identified_worker", "1", "1"] and line[-2:] == ["1001", "1004"] for line in edges), edges

stacks = [line for line in lines if len(line) >= 3 and line[:3] == ["ELISA_PROFILE", "1", "stack"]]
assert any(line[3] == "identified_main;identified_worker" and line[-1] == "1001;1004" for line in stacks), stacks

recent = [line for line in lines if len(line) >= 3 and line[:3] == ["ELISA_PROFILE", "1", "path"]]
assert any(line[5] == "identified_main" and line[-1] == "1001" for line in recent), recent
assert any(line[5] == "identified_main" and line[7] == "counter" and line[-1] == "1003" for line in recent), recent
assert lines[-1][:3] == ["ELISA_PROFILE", "1", "end"], lines[-1]
print("collector identity smoke OK")
PY
