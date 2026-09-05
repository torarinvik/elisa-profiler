#!/usr/bin/env python3
"""Validate the structural invariants of a native Speedscope artifact."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: speedscope_smoke.py ARTIFACT")
    artifact = Path(sys.argv[1])
    report = json.loads(artifact.read_text(encoding="utf-8"))
    assert report["$schema"].endswith("file-format-schema.json")
    assert report["activeProfileIndex"] == 0
    assert report["shared"]["frames"]
    profile = report["profiles"][0]
    assert profile["type"] == "sampled"
    assert profile["unit"] == "nanoseconds"
    assert len(profile["samples"]) == len(profile["weights"])
    assert profile["endValue"] == sum(profile["weights"])
    assert profile["endValue"] > 0
    assert all(
        0 <= frame_index < len(report["shared"]["frames"])
        for sample in profile["samples"]
        for frame_index in sample
    )
    print("native speedscope smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
