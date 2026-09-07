#!/usr/bin/env python3
"""Verify conservative reuse of an already-instrumented Elisa executable."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str], expected: int = 0) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != expected:
        raise AssertionError(
            f"command returned {completed.returncode}, expected {expected}: {' '.join(command)}\n"
            f"stdout={completed.stdout}\nstderr={completed.stderr}"
        )
    return completed


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: prebuilt_smoke.py NATIVE_PROFILER")
    profiler = Path(sys.argv[1]).resolve()
    root = Path(__file__).resolve().parent.parent
    source = root / "examples" / "hot_loop.elisa"

    with tempfile.TemporaryDirectory(prefix="elisa-profiler-prebuilt-") as directory:
        work = Path(directory)
        cache = work / "cache"
        first = work / "first.json"
        run([
            str(profiler), "profile", str(source), "--cache-dir", str(cache),
            "--format", "json", "--output", str(first),
        ])
        programs = list(cache.glob("*.program"))
        assert len(programs) == 1, programs
        prebuilt = programs[0].resolve()

        reused = work / "prebuilt.json"
        run([
            str(profiler), "profile", str(source), "--prebuilt", str(prebuilt),
            "--format", "json", "--output", str(reused),
        ])
        report = json.loads(reused.read_text(encoding="utf-8"))
        run([
            sys.executable, str(root / "test" / "profile_schema_smoke.py"),
            str(root / "docs" / "profile.schema.json"), str(reused),
        ])
        assert report["target"] == {
            "build_kind": "prebuilt",
            "executable": str(prebuilt),
        }
        assert report["run"]["compile_ms"] == 0.0
        assert report["summary"]["function_events"] > 0

        rejected = run([
            str(profiler), "profile", str(source), "--prebuilt", "/bin/true",
            "--format", "json",
        ], expected=2)
        assert "not a compatible Elisa instrumented target" in rejected.stderr

        relative = run([
            str(profiler), "profile", str(source), "--prebuilt", "bin/elisa-profiler",
            "--format", "json",
        ], expected=2)
        assert "absolute executable path" in relative.stderr

    print("prebuilt smoke OK: validated reuse and rejected incompatible targets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
