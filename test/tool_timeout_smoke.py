#!/usr/bin/env python3
"""Tool bounds are explicit, finite, and independent of target timeout."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
native = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "bin/elisa-profiler"
with tempfile.TemporaryDirectory(prefix="elisa-profiler-tool-bound-") as directory:
    work = Path(directory)
    marker = work / "compiler-started"
    compiler = work / "slow compiler"
    compiler.write_text(
        "#!/bin/sh\n"
        'touch "$ELISA_TIMEOUT_TEST_MARKER"\n'
        "exec /bin/sleep 30\n", encoding="utf-8",
    )
    compiler.chmod(0o755)
    environment = os.environ | {
        "ELISA_COMPILER_SCRIPT": str(compiler),
        "ELISA_TIMEOUT_TEST_MARKER": str(marker),
    }
    command = [str(native), "profile", str(ROOT / "examples/hot_loop.elisa"), "--format", "json"]
    for invalid in ("", "0", "-1", "nan", "inf", "1800.1", "999999999999999999999"):
        result = subprocess.run(command, env=environment | {
            "ELISA_PROFILER_TOOL_TIMEOUT_SECONDS": invalid,
        }, capture_output=True, timeout=10)
        assert result.returncode == 2, (invalid, result)
        assert b"ELISA_PROFILER_TOOL_TIMEOUT_SECONDS" in result.stderr, result.stderr
        assert not marker.exists(), "invalid bound launched compiler"
    start = time.monotonic()
    result = subprocess.run(command, env=environment | {
        "ELISA_PROFILER_TOOL_TIMEOUT_SECONDS": "0.5",
    }, capture_output=True, timeout=10)
    assert result.returncode == 2, result
    assert marker.exists(), result.stderr
    assert time.monotonic() - start < 5, "tool timeout was not enforced"
print("tool timeout smoke OK: invalid bounds rejected and stalled compiler terminated")
