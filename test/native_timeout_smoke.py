#!/usr/bin/env python3
"""Verify the Elisa-native launcher enforces timeout and records its cause."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    native = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "bin" / "elisa-profiler"
    with tempfile.TemporaryDirectory(prefix="elisa-profiler-native-timeout-") as directory:
        report = Path(directory) / "timeout.json"
        command = [
            str(native),
            "profile",
            str(ROOT / "examples" / "timeout.elisa"),
            "--timeout",
            "0.05",
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
            start_new_session=(os.name == "posix"),
        )
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            stdout, stderr = process.communicate()
            raise AssertionError(
                "native timeout probe did not finish; "
                f"stdout={stdout[-500:]!r} stderr={stderr[-500:]!r}"
            )
        assert process.returncode == 143, (process.returncode, stdout, stderr)
        payload = json.loads(report.read_text(encoding="utf-8"))
        assert payload["summary"]["capture_complete"] is False, payload["summary"]
        assert payload["run"]["timeout_s"] == 0.05, payload["run"]
        assert payload["run"]["exit_code"] is None, payload["run"]
        assert payload["run"]["signal"] == 15, payload["run"]
        assert payload["run"]["repetitions"][0]["timed_out"] is True, payload["run"]
        assert "timeout" in payload["quality"]["reasons"], payload["quality"]
        assert payload["quality"]["capture"] == "target_signal", payload["quality"]
    print("native timeout smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
