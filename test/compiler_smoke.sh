#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
COMPILER="${ELISA_COMPILER_WRAPPER:-$ROOT/scripts/elisa-compiler}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$COMPILER" ]] || { echo "compiler wrapper missing: $COMPILER" >&2; exit 2; }
[[ -x "${ELISA_COMPILER_ROOT:-$ROOT/../elisa-compiler-worktrees/profiler}/bin/elisac-stage1" ]] || {
    echo "stage1 compiler is not seeded; run make compiler-seed" >&2
    exit 2
}

"$COMPILER" -o "$WORK/hello.o" "$ROOT/examples/hello.elisa" >"$WORK/compiler.log" 2>&1
test -s "$WORK/hello.o"
echo "compiler smoke OK"
