#!/usr/bin/env python3
"""Validate the summary comparison emitted by the Elisa-native CLI."""

from __future__ import annotations

import json
from pathlib import Path
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} COMPARISON_JSON")
    report = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    assert report["kind"] == "profile_comparison"
    assert report["schema_version"] == 2
    assert report["envelope"] == {
        "major": 2,
        "minor": 0,
        "kind": "comparison",
        "compatibility": "backward-compatible-v1",
    }
    assert report["baseline"]["source"] == report["candidate"]["source"]
    assert report["baseline"]["compiler_commit"] == report["candidate"]["compiler_commit"]
    assert report["metrics"]["execution_ms_mean"]["baseline"] > 0
    assert report["metrics"]["execution_ms_mean"]["candidate"] > 0
    assert report["metrics"]["events"]["delta"] == 0
    assert report["metrics"]["dropped_events"]["baseline"] == 0
    assert report["metrics"]["dropped_events"]["candidate"] == 0
    assert report["warnings"] == [
        "one or both captures contain incomplete or bounded evidence"
    ]
    assert report["status"] == "warning"
    print("native comparison smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
