#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

CC="${ELISA_CLANG:-clang}"
for timing_name in untimed timed; do
    if test "$timing_name" = timed; then
        "$CC" -std=c11 -O2 -fno-builtin -pthread -DELISA_PROFILE_TIMING=1 \
            -o "$WORK/overflow-$timing_name" \
            "$ROOT/scripts/profiler_runtime.c" "$ROOT/test/overflow_mismatch_smoke.c"
    else
        "$CC" -std=c11 -O2 -fno-builtin -pthread \
            -o "$WORK/overflow-$timing_name" \
            "$ROOT/scripts/profiler_runtime.c" "$ROOT/test/overflow_mismatch_smoke.c"
    fi

    ELISA_OVERFLOW_MODE=valid "$WORK/overflow-$timing_name" 2>"$WORK/$timing_name-valid.txt"
    ELISA_OVERFLOW_MODE=mismatch "$WORK/overflow-$timing_name" 2>"$WORK/$timing_name-mismatch.txt"
done

python3 - "$WORK" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
for timing_name in ("untimed", "timed"):
    for mode, expected_completed in (("valid", 1025), ("mismatch", 0)):
        records = [
            line.rstrip("\n").split("\t")
            for line in (root / f"{timing_name}-{mode}.txt").read_text(encoding="utf-8").splitlines()
            if line.startswith("ELISA_PROFILE\t")
        ]
        meta = next(record for record in records if record[2] == "meta")
        assert int(meta[6]) == 1024, meta
        assert int(meta[7]) > 0, meta
        function = next(record for record in records if record[2] == "location" and record[3] == "3")
        assert function[4:7] == ["deep", "1", "1025"], function
        assert int(function[11]) == expected_completed, function
print("overflow mismatch smoke OK")
PY
