#!/usr/bin/env python3
"""Verbose target output stays bounded, explicit, and recoverable by opt-in."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
native = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "bin/elisa-profiler"
OUTPUT_LINE = "0123456789abcdef\n"
LINES = 70000

with tempfile.TemporaryDirectory(prefix="elisa-profiler-output-budget-") as directory:
    work = Path(directory)
    source = work / "verbose.elisa"
    source.write_text(
        '@link_name("puts")\n'
        'extern budget_puts(message: cstr) -> i32 can[Console]\n'
        'def main() -> i64 can[Console]:\n'
        '    index: mutable i64 = 0\n'
        f'    while index < {LINES} |index|:\n'
        '        _ = budget_puts("0123456789abcdef")\n'
        '        index <- index + 1\n'
        '    return 0\n', encoding="utf-8",
    )
    report = work / "report.json"
    command = [str(native), "profile", str(source), "--mode", "functions",
               "--format", "json", "--cache-dir", str(work / "cache"), "--output", str(report)]
    clean_environment = dict(os.environ)
    clean_environment.pop("ELISA_PROFILER_MAX_PROGRAM_OUTPUT_BYTES", None)

    def run(environment):
        result = subprocess.run(command, env=environment, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stderr
        return json.loads(report.read_text(encoding="utf-8"))

    default = run(clean_environment)
    assert default["program_output_byte_limit"] == 1048576
    assert len(default["program_stdout"]) == 1048576
    assert default["program_stdout_truncated"] is True
    raised = run(clean_environment | {"ELISA_PROFILER_MAX_PROGRAM_OUTPUT_BYTES": "2097152"})
    assert raised["program_output_byte_limit"] == 2097152
    assert raised["program_stdout"] == OUTPUT_LINE * LINES, (
        len(raised["program_stdout"]), raised["program_stdout_truncated"],
        raised["program_stdout"][:80], raised["program_stdout"][-80:],
    )
    assert raised["program_stdout_truncated"] is False
    tiny = run(clean_environment | {"ELISA_PROFILER_MAX_PROGRAM_OUTPUT_BYTES": "1"})
    assert tiny["program_stdout"] == "0" and tiny["program_stdout_truncated"] is True
    exact = run(clean_environment | {"ELISA_PROFILER_MAX_PROGRAM_OUTPUT_BYTES": str(len(OUTPUT_LINE) * LINES)})
    assert exact["program_stdout"] == OUTPUT_LINE * LINES
    assert exact["program_stdout_truncated"] is False
    maximum = run(clean_environment | {"ELISA_PROFILER_MAX_PROGRAM_OUTPUT_BYTES": "16777216"})
    assert maximum["program_stdout"] == OUTPUT_LINE * LINES
    assert maximum["program_stdout_truncated"] is False
    for invalid in ("", "0", "-1", "nan", "16777217", "999999999999999999999"):
        result = subprocess.run(command, env=clean_environment | {
            "ELISA_PROFILER_MAX_PROGRAM_OUTPUT_BYTES": invalid,
        }, capture_output=True, timeout=10)
        assert result.returncode == 2, (invalid, result)
        assert b"ELISA_PROFILER_MAX_PROGRAM_OUTPUT_BYTES" in result.stderr
print("program output budget smoke OK: default, explicit bounds, truncation, and malformed controls")
