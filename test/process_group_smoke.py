#!/usr/bin/env python3
"""Verify the Elisa-native timeout cleanup terminates target descendants."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
CHILD_MARKER = "elisa-profiler-process-group-child"
NATIVE_TIMEOUT_SECONDS = "0.05"
PROBE_WAIT_SECONDS = 0.5
EXPECTED_SIGNAL_EXIT_STATUS = 143


def marked_processes() -> list[str]:
    result = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if CHILD_MARKER in line]


def main() -> int:
    if os.name != "posix":
        print("process-group smoke SKIP: POSIX process groups unavailable")
        return 0

    with tempfile.TemporaryDirectory(prefix="elisa-profiler-process-group-") as directory:
        root = Path(directory)
        report = root / "process-group.json"
        native = ROOT / "bin" / "elisa-profiler"
        command = [
            str(native),
            "profile",
            str(ROOT / "examples" / "native_process_group_probe.elisa"),
            "--timeout",
            NATIVE_TIMEOUT_SECONDS,
            "--format",
            "json",
            "--output",
            str(report),
        ]
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == EXPECTED_SIGNAL_EXIT_STATUS, (process.returncode, stdout, stderr)
        payload = report.read_text(encoding="utf-8")
        assert '"timed_out":true' in payload, payload
        time.sleep(PROBE_WAIT_SECONDS)
        assert not marked_processes(), marked_processes()

    print("process-group cleanup OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
