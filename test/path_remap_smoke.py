#!/usr/bin/env python3
"""Verify report path remapping preserves local recovery provenance."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
TIMEOUT_SECONDS = 120
DISPLAY_PREFIX = "PROJECT"


def main() -> int:
    native = Path(sys.argv[1]) if len(sys.argv) == 2 else ROOT / "bin" / "elisa-profiler"
    source = (ROOT / "examples" / "hot_loop.elisa").resolve()
    with tempfile.TemporaryDirectory(prefix="elisa-profiler-path-remap-") as directory:
        output = Path(directory) / "remapped.json"
        process = subprocess.run(
            [
                str(native),
                "profile",
                str(source),
                "--path-map",
                f"{ROOT.resolve()}={DISPLAY_PREFIX}",
                "--format",
                "json",
                "--output",
                str(output),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=TIMEOUT_SECONDS,
        )
        if process.returncode != 0:
            raise SystemExit(f"path-remapped capture failed: {process.stderr or process.stdout}")
        report = json.loads(output.read_text(encoding="utf-8"))
        expected = f"{DISPLAY_PREFIX}/examples/hot_loop.elisa"
        if report["source"] != expected:
            raise SystemExit(f"report source was not remapped: {report['source']!r}")
        if not report["locations"]:
            raise SystemExit("path-remapped report omitted locations")
        if any(location["source"] != expected for location in report["locations"]):
            raise SystemExit("location source paths were not remapped consistently")
        manifest = json.loads(Path(f"{output}.manifest.json").read_text(encoding="utf-8"))
        if manifest["source"] != str(source):
            raise SystemExit("capture manifest lost the raw recovery source path")
        invalid = subprocess.run(
            [str(native), "profile", str(source), "--path-map", "missing", "--format", "json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=TIMEOUT_SECONDS,
        )
        if invalid.returncode == 0:
            raise SystemExit("invalid path mapping was accepted")
    print("path remapping smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
