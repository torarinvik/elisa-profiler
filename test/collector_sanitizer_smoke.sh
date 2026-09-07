#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CC="${ELISA_CLANG:-clang}"

if ! "$CC" -fsanitize=address,undefined -x c - -o /dev/null <<'EOF'
int main(void) { return 0; }
EOF
then
    echo "collector sanitizer smoke skipped: compiler lacks address/undefined sanitizers"
    exit 0
fi

WORK="$(mktemp -d "${ELISA_TEST_TMPDIR:-/tmp}/elisa-profiler-sanitizer.XXXXXX")"
cleanup() {
    # Darwin clang emits a sibling .dSYM directory for each linked binary;
    # remove only the contents of this freshly-created temporary directory.
    find "$WORK" -depth -mindepth 1 -delete
    rmdir "$WORK"
}
trap cleanup EXIT INT TERM HUP

SANITIZER_CFLAGS=(
    -std=c11 -O1 -g -fno-builtin -fno-omit-frame-pointer
    -fsanitize=address,undefined -pthread
)

"$CC" "${SANITIZER_CFLAGS[@]}" \
    -o "$WORK/collector-regression" \
    "$ROOT/test/collector_regression_smoke.c"
"$CC" "${SANITIZER_CFLAGS[@]}" \
    -o "$WORK/collector-content" \
    "$ROOT/scripts/profiler_runtime.c" \
    "$ROOT/test/collector_content_smoke.c"
"$CC" "${SANITIZER_CFLAGS[@]}" \
    -o "$WORK/collector-concurrency" \
    "$ROOT/scripts/profiler_runtime.c" \
    "$ROOT/test/profile_fd_target.c"

ASAN_OPTIONS=detect_leaks=0:halt_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1 \
    "$WORK/collector-regression" >"$WORK/regression.log" 2>&1
ASAN_OPTIONS=detect_leaks=0:halt_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1 \
    "$WORK/collector-content" >"$WORK/content.log" 2>&1
ASAN_OPTIONS=detect_leaks=0:halt_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1 \
    "$WORK/collector-concurrency" >"$WORK/concurrency.log" 2>&1

grep -Fq "collector regression smoke OK" "$WORK/regression.log"
grep -Fq $'ELISA_PROFILE\t1\tbegin\t1' "$WORK/content.log"
grep -Fq $'ELISA_PROFILE\t1\tend\t1' "$WORK/content.log"
grep -Fq "target diagnostic" "$WORK/concurrency.log"
grep -Fq $'ELISA_PROFILE\t1\tend\t1' "$WORK/concurrency.log"
echo "collector sanitizer smoke OK"
