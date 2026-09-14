#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
for timing in 0 1; do
    clang -std=c11 -O2 -Wall -Werror -fno-builtin -pthread -DELISA_PROFILE_TIMING="$timing" \
        "$ROOT/scripts/profiler_runtime.c" "$ROOT/test/collector_allocation_site_smoke.c" -o "$WORK/test"
    ELISA_PROFILE_MODE=full "$WORK/test" 2> "$WORK/trace"
    python3 - "$WORK/trace" <<'PY'
import sys
rows=[l.rstrip().split('\t') for l in open(sys.argv[1])]
sites=sorted([r[5:] for r in rows if r[2:5]==['extension','allocation_site','1']], key=lambda r:int(r[0]))
assert sites == [
 ['0','0','0','0','0','0','0','-'],
 ['1','1','200','23','18446744073709551600','12','0','18446744073709551600:12;200:23'],
 ['2','1','18446744073709551600','12','0','0','0','18446744073709551600:12'],
 ['3','0','0','0','0','0','0','-'],
 ['4','1','1000','55','0','0','0','1000:55'],
 ['5','1','509','59','508','58','2',';'.join(f'{500+i}:{50+i}' for i in range(2,10))],
 ['6','0','0','0','0','0','0','-'],
], sites
assert len([r for r in rows if r[2]=='allocation'])==7
print('allocation site collector PASS')
PY
done
