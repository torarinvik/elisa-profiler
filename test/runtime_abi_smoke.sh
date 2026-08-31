#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

CC="${ELISA_CLANG:-clang}"
"$CC" -std=c11 -O2 -fno-builtin -pthread -DELISA_PROFILE_NO_MAIN \
    -c -o "$WORK/profiler-runtime.o" "$ROOT/scripts/profiler_runtime.c"
"$CC" -std=c11 -O2 -fno-builtin -pthread \
    -o "$WORK/va-copy-abi" \
    "$ROOT/test/va_copy_abi_smoke.c" "$WORK/profiler-runtime.o"
"$WORK/va-copy-abi"

echo "runtime ABI smoke OK"
