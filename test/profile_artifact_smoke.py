#!/usr/bin/env python3
"""Validate the v1 profile artifact envelope and its embedded report."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: profile_artifact_smoke.py ARTIFACT")
    artifact_path = Path(sys.argv[1])
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["artifact_version"] == 1
    assert artifact["kind"] == "elisa-profile"
    assert artifact["manifest"]["capture_format"] == "profile-json-v1"
    assert artifact["manifest"]["compression"] == "none"
    capture = artifact["capture"]
    assert capture["schema_version"] == 1
    assert capture["quality"]["capture"] in {
        "complete", "target_exit", "target_signal", "profiler_failure"
    }
    encoded = json.dumps(capture, ensure_ascii=False, separators=(",", ":"))
    assert artifact["manifest"]["capture_bytes"] > 0
    assert encoded
    print("profile artifact smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
