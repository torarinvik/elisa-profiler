#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CC=${ELISA_CLANG:-clang}
ITERATIONS=${ELISA_CALLBACK_BENCHMARK_ITERATIONS:-100000}
REPETITIONS=${ELISA_CALLBACK_BENCHMARK_REPETITIONS:-5}
OUTPUT=${1:-"$ROOT/build/collector-callback-benchmark.tsv"}
EXPECTED_VARIANT_COUNT=6
WORK=$(mktemp -d "${ELISA_TEST_TMPDIR:-/tmp}/elisa-profiler-callback-benchmark.XXXXXX")
trap 'rm -rf "$WORK"' EXIT HUP INT TERM

mkdir -p "$(dirname -- "$OUTPUT")"
{
    printf '# host\t%s\n' "$(uname -srm)"
    printf '# compiler\t%s\n' "$($CC --version | sed -n '1p')"
    printf '# iterations\t%s\n' "$ITERATIONS"
    printf '# repetitions\t%s\n' "$REPETITIONS"
    printf 'variant\trepetition\tcallbacks\telapsed_ns\tns_per_callback\n'
} >"$OUTPUT"

build_and_run() {
    index=$1
    name=$2
    mode=$3
    timing=$4
    event_trace=$5
    binary="$WORK/$name"
    "$CC" -std=c11 -O2 -fno-builtin -pthread \
        -DBENCHMARK_VARIANT="$index" $timing \
        -o "$binary" "$ROOT/scripts/profiler_runtime.c" \
        "$ROOT/test/collector_callback_benchmark.c"
    ELISA_PROFILE_FD=2 \
    ELISA_PROFILE_MODE="$mode" \
    ELISA_PROFILE_EVENT_TRACE="$event_trace" \
    ELISA_PROFILE_MAX_CAPTURE_BYTES=0 \
    ELISA_CALLBACK_BENCHMARK_ITERATIONS="$ITERATIONS" \
    ELISA_CALLBACK_BENCHMARK_REPETITIONS="$REPETITIONS" \
        "$binary" 2>/dev/null >>"$OUTPUT"
}

build_and_run 0 empty diagnostic '' 0
build_and_run 1 count-only statements '' 0
build_and_run 2 function-timing functions -DELISA_PROFILE_TIMING=1 0
build_and_run 3 statement-timing statements -DELISA_PROFILE_TIMING=1 0
build_and_run 4 scalar values '' 0
build_and_run 5 full-trace full '' 1

awk -v expected_repetitions="$REPETITIONS" -v expected_variants="$EXPECTED_VARIANT_COUNT" '
    /^#/ || /^variant[[:space:]]/ { next }
    NF != 5 || $3 !~ /^[0-9]+$/ || $4 !~ /^[0-9]+$/ || $5 !~ /^[0-9]+$/ { bad = 1 }
    count[$1] += 1
    total += 1
    END {
        if (bad || total != expected_repetitions * expected_variants) {
            exit 1
        }
        for (variant in count) {
            if (count[variant] != expected_repetitions) {
                exit 1
            }
        }
    }
' "$OUTPUT"

printf 'collector callback benchmark: %s\n' "$OUTPUT"
