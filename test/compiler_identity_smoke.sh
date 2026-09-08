#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
COMPILER_ROOT="${ELISA_COMPILER_ROOT:-$ROOT/../elisa-compiler-worktrees/profiler}"
STAGE1="${ELISA_STAGE1_BIN:-$COMPILER_ROOT/bin/elisac-stage1}"
WRAPPER="$COMPILER_ROOT/scripts/elisac_stage1.sh"
WORK="$(mktemp -d "${ELISA_TEST_TMPDIR:-/tmp}/elisa-profiler-compiler-identity.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

test -x "$STAGE1"
test -x "$WRAPPER"

cat >"$WORK/identity.elisa" <<'ELISA'
def helper(value: i64) -> i64:
    next: i64 = value + 1
    return next

def main() -> i64:
    return helper(41)
ELISA

ELISA_STAGE1_BIN="$STAGE1" ELISA_COMPILER_ROOT="$COMPILER_ROOT" \
    "$WRAPPER" -emit llvm -g -ftrace -O0 -o "$WORK/first.ll" "$WORK/identity.elisa"
ELISA_STAGE1_BIN="$STAGE1" ELISA_COMPILER_ROOT="$COMPILER_ROOT" \
    "$WRAPPER" -emit llvm -g -ftrace -O0 -o "$WORK/second.ll" "$WORK/identity.elisa"

ELISA_STAGE1_BIN="$STAGE1" ELISA_COMPILER_ROOT="$COMPILER_ROOT" \
python3 - "$WORK/first.ll" "$WORK/second.ll" "$WRAPPER" "$WORK/identity.elisa" <<'PY'
import re
import sys
import subprocess
from pathlib import Path

declarations = {
    "elisa_trace_record_id(ptr, i32, i64)",
    "elisa_trace_function_entry_id(ptr, i32, i64)",
    "elisa_trace_function_exit_id(ptr, i32, i64)",
    "elisa_trace_record_value_id(ptr, i32, i64, ptr, i64, i32)",
}
call_pattern = re.compile(
    r"call void @(?P<name>elisa_trace_(?:record_id|function_entry_id|function_exit_id|record_value_id))"
    r"\([^\n]*?i64 (?P<id>-?\d+)\)"
)

def identity_evidence(path: str):
    text = open(path, encoding="utf-8").read()
    found = {
        match.group(1).removeprefix("elisa_trace_")
        for match in re.finditer(r"declare void @([^\(]+)\(([^\)]*)\)", text)
        if f"{match.group(1)}({match.group(2)})" in declarations
    }
    calls = [(match.group("name"), int(match.group("id"))) for match in call_pattern.finditer(text)]
    expected = {item.split("(", 1)[0].removeprefix("elisa_trace_") for item in declarations}
    assert found == expected, found
    assert len(calls) >= 5, calls
    assert all(identity != 0 for _, identity in calls), calls
    return calls

first = identity_evidence(sys.argv[1])
second = identity_evidence(sys.argv[2])
assert first == second, (first, second)
function_callbacks = {"elisa_trace_function_entry_id", "elisa_trace_function_exit_id"}
expected_functions = [call for call in first if call[0] in function_callbacks]
for index, (flags, functions_only) in enumerate([
    (["-ftrace-functions"], True),
    (["-ftrace", "-ftrace-functions"], True),
    (["-ftrace-functions", "-ftrace"], False),
]):
    output = Path(sys.argv[1]).with_name(f"trace-mode-{index}.ll")
    subprocess.run([sys.argv[3], "-emit", "llvm", "-g", *flags, "-O0",
                    "-o", str(output), sys.argv[4]], check=True, timeout=60)
    emitted = output.read_text(encoding="utf-8")
    calls = [(match.group("name"), int(match.group("id")))
             for match in call_pattern.finditer(emitted)]
    assert [call for call in calls if call[0] in function_callbacks] == expected_functions
    records = re.findall(r"call void @elisa_trace_record(?:_value)?_id\(", emitted)
    assert bool(records) is not functions_only, (flags, records)
print("compiler identity smoke OK")
PY
