#!/usr/bin/env python3
"""Verify explicit native baseline promotion and collision safety."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent.parent
NATIVE = ROOT / "bin" / "elisa-profiler"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="elisa-baseline-") as directory:
        work = Path(directory)
        capture = work / "capture.json"
        store = work / "baselines"
        profile = subprocess.run(
            [str(NATIVE), "profile", str(ROOT / "examples" / "hot_loop.elisa"),
             "--format", "json", "--output", str(capture)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            check=False,
        )
        assert profile.returncode == 0, (profile.stdout, profile.stderr)
        promoted = subprocess.run(
            [str(NATIVE), "baseline", "promote", str(capture), "--store", str(store),
             "--name", "release-1", "--reason", "validated reference workload"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            check=False,
        )
        assert promoted.returncode == 0, (promoted.stdout, promoted.stderr)
        metadata_path = store / "release-1.json"
        baseline_path = store / "release-1.elisaprof"
        metadata_bytes = metadata_path.read_bytes()
        metadata = json.loads(metadata_bytes)
        assert metadata["kind"] == "elisa_profiler_baseline"
        assert metadata["name"] == "release-1"
        assert metadata["capture"] == "release-1.elisaprof"
        assert metadata["outcome"] == "success"
        assert baseline_path.read_bytes() == capture.read_bytes()
        schema_check = subprocess.run(
            ["python3", str(ROOT / "test" / "profile_schema_smoke.py"),
             str(ROOT / "docs" / "baseline.schema.json"), str(metadata_path)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        assert schema_check.returncode == 0, (schema_check.stdout, schema_check.stderr)

        rejected = subprocess.run(
            [str(NATIVE), "baseline", "promote", str(capture), "--store", str(store),
             "--name", "release-1", "--reason", "accidental duplicate"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            check=False,
        )
        assert rejected.returncode == 2, rejected
        assert metadata_path.read_bytes() == metadata_bytes
        invalid = subprocess.run(
            [str(NATIVE), "baseline", "promote", str(capture), "--store", str(store),
             "--name", "../escape", "--reason", "invalid name"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            check=False,
        )
        assert invalid.returncode == 2, invalid
        assert not (work / "escape.elisaprof").exists()
    print("baseline smoke OK")


if __name__ == "__main__":
    main()
