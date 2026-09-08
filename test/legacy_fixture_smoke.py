#!/usr/bin/env python3
"""Keep v1 migration coverage pinned to input not produced by the v2 writer."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "test" / "fixtures" / "legacy" / "profile-v1.json"
EXPECTED_REPORT_PREFIX = b"Elisa profiler"
EXPECTED_FOLDED = b"root;work 123\n"
EXPECTED_SCHEMA_VERSION = 2
EXPECTED_COMPARISON_STATUS = "ok"


def run(native: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(native), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def main() -> int:
    native = Path(sys.argv[1]) if len(sys.argv) == 2 else ROOT / "bin" / "elisa-profiler"
    assert json.loads(FIXTURE.read_bytes())["schema_version"] == 1

    text = run(native, "report", str(FIXTURE), "--format", "text")
    assert text.returncode == 0, (text.returncode, text.stderr)
    assert text.stdout.startswith(EXPECTED_REPORT_PREFIX), text.stdout

    folded = run(native, "report", str(FIXTURE), "--format", "folded")
    assert folded.returncode == 0, (folded.returncode, folded.stderr)
    assert folded.stdout == EXPECTED_FOLDED, folded.stdout

    comparison = run(native, "compare", str(FIXTURE), str(FIXTURE), "--format", "json")
    assert comparison.returncode == 0, (comparison.returncode, comparison.stderr)
    normalized = json.loads(comparison.stdout)
    assert normalized["schema_version"] == EXPECTED_SCHEMA_VERSION, normalized
    assert normalized["status"] == EXPECTED_COMPARISON_STATUS, normalized

    print("frozen legacy fixture smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
