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
        assert payload["run"]["outcome"] == "timeout", payload["run"]
        assert payload["quality"]["capture"] == "timeout", payload["quality"]
        assert payload["summary"]["capture_complete"] is False, payload["summary"]
        assert payload["run"]["timeout_s"] == 0.05, payload["run"]
        assert payload["run"]["exit_code"] is None, payload["run"]
        assert payload["run"]["signal"] == 15, payload["run"]
        assert payload["run"]["repetitions"][0]["timed_out"] is True, payload["run"]
        assert "timeout" in payload["quality"]["reasons"], payload["quality"]
        manifest = json.loads(Path(str(report) + ".manifest.json").read_text(encoding="utf-8"))
        assert manifest["state"] == "partial", manifest
        assert manifest["capture_complete"] is False, manifest
        text_report = subprocess.run(
            [str(native), "report", report, "--format", "text"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert text_report.returncode == 0, (text_report.returncode, text_report.stderr)
        assert b"outcome: timeout" in text_report.stdout, text_report.stdout
        assert b"capture completeness: partial" in text_report.stdout, text_report.stdout
        assert manifest["completed_repetitions"] == 1, manifest
        capture_index = manifest["capture_index"]
        assert capture_index["format"] == "record-framed-v1", capture_index
        assert capture_index["bytes"] >= capture_index["valid_bytes"] >= 0, capture_index
        assert capture_index["valid_frames"] >= 0, capture_index
    print("native timeout smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
