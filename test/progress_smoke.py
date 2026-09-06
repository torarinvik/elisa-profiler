#!/usr/bin/env python3
"""Verify the native progress channel and report stdout separation."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "docs" / "progress.schema.json"
TIMEOUT_SECONDS = 120
EXPECTED_REPORT_SCHEMA_VERSION = 2
EXPECTED_PROGRESS_SCHEMA_VERSION = 1
EXPECTED_REPETITIONS = 2
EXPECTED_WARMUPS = 1


def main() -> int:
    native = Path(sys.argv[1]) if len(sys.argv) == 2 else ROOT / "bin" / "elisa-profiler"
    with tempfile.TemporaryDirectory(prefix="elisa-profiler-progress-") as directory:
        work = Path(directory)
        progress = work / "progress.json"
        process = subprocess.run(
            [
                str(native),
                "profile",
                str(ROOT / "examples" / "hot_loop.elisa"),
                "--repeat",
                str(EXPECTED_REPETITIONS),
                "--warmup",
                str(EXPECTED_WARMUPS),
                "--progress",
                str(progress),
                "--format",
                "json",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=TIMEOUT_SECONDS,
        )
        if process.returncode != 0:
            raise SystemExit(f"progress capture failed: {process.stderr or process.stdout}")
        report = json.loads(process.stdout)
        status = json.loads(progress.read_text(encoding="utf-8"))
        if report["schema_version"] != EXPECTED_REPORT_SCHEMA_VERSION:
            raise SystemExit("progress smoke received an unexpected report schema")
        if report["envelope"] != {
            "major": 2,
            "minor": 0,
            "kind": "profile",
            "compatibility": "backward-compatible-v1",
        }:
            raise SystemExit("progress smoke received an unexpected report envelope")
        if status["kind"] != "elisa_profile_progress":
            raise SystemExit("progress status kind is incorrect")
        if status["schema_version"] != EXPECTED_PROGRESS_SCHEMA_VERSION:
            raise SystemExit("progress status schema version is incorrect")
        if status["state"] != "complete":
            raise SystemExit(f"progress status did not finish: {status}")
        if status["repetition"] != EXPECTED_REPETITIONS:
            raise SystemExit("progress status has the wrong measured repetition")
        if status["requested_repetitions"] != EXPECTED_REPETITIONS:
            raise SystemExit("progress status has the wrong repetition budget")
        if status["elapsed_ns"] <= 0 or status["events"] <= 0 or status["valid_frames"] <= 0:
            raise SystemExit("progress status omitted positive capture evidence")
        if not status["capture_started"] or not status["capture_complete"]:
            raise SystemExit("progress status did not report a complete capture")
        schema_check = subprocess.run(
            [sys.executable, str(ROOT / "test" / "profile_schema_smoke.py"), str(SCHEMA), str(progress)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        if schema_check.returncode != 0:
            raise SystemExit(f"progress schema check failed: {schema_check.stderr or schema_check.stdout}")
    print("progress channel smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
