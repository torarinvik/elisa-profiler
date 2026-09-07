#!/usr/bin/env python3
"""Validate the v1 artifact envelope and its embedded v2 report."""

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
    assert artifact["manifest"]["capture_format"] == "profile-json-v2"
    assert artifact["manifest"]["compression"] == "none"
    capture = artifact["capture"]
    assert capture["schema_version"] == 2
    assert capture["envelope"] == {
        "major": 2,
        "minor": 0,
        "kind": "profile",
        "compatibility": "backward-compatible-v1",
    }
    assert capture["quality"]["capture"] in {
        "complete", "target_exit", "target_signal", "timeout", "profiler_failure", "recovered"
    }
    compiler = capture["compiler"]
    assert compiler["manifest"]
    assert compiler["stage1_binary"]
    assert len(compiler["stage1_sha256"]) == 64
    assert len(compiler["runtime_object_sha256"]) == 64
    encoded = json.dumps(capture, ensure_ascii=False, separators=(",", ":"))
    assert artifact["manifest"]["capture_bytes"] > 0
    assert encoded
    print("profile artifact smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
