#!/usr/bin/env python3
"""Check the local compiler manifest and its content/flag invalidation behavior."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"compiler manifest smoke failed: {message}")


def main() -> int:
    if len(sys.argv) != 3:
        fail("usage: compiler_manifest_smoke.py MANIFEST.json WRITER.py")
    manifest_path = Path(sys.argv[1]).resolve()
    writer = Path(sys.argv[2]).resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        fail(f"cannot read manifest: {error}")
    required = {
        "format",
        "kind",
        "compiler",
        "inputs_sha256",
        "source_sha256",
        "seed_identity",
        "stage0",
        "stage1",
        "runtime",
        "build_flags",
        "toolchain",
        "architecture",
        "abi",
        "freshness",
    }
    if not isinstance(manifest, dict) or not required.issubset(manifest):
        fail("manifest is missing required provenance fields")
    if manifest["format"] != 1 or manifest["kind"] != "elisa_profiler_compiler_build_manifest":
        fail("unexpected manifest identity")
    freshness = manifest["freshness"]
    if not freshness.get("usable") or freshness.get("reasons"):
        fail(f"manifest is not usable: {freshness.get('reasons')}")
    compiler = manifest["compiler"]
    stage0 = manifest["stage0"].get("path")
    seed_flag = "--seed-opt-level=" + manifest["build_flags"]["seed_optimization"]
    command = [
        sys.executable,
        str(writer),
        "--compiler-root",
        compiler["root"],
        "--stage1",
        manifest["stage1"]["path"],
        "--runtime",
        manifest["runtime"]["path"],
        "--output",
        str(manifest_path),
        seed_flag,
        "--seed-max-rss-kb",
        str(manifest["build_flags"]["seed_max_rss_kb"]),
        "--native-opt-level=" + manifest["build_flags"]["native_optimization"],
        "--check",
    ]
    if stage0:
        command.extend(["--stage0", stage0])
    current = subprocess.run(command, capture_output=True, text=True, check=False)
    if current.returncode != 0:
        fail(f"current manifest did not validate: {current.stderr.strip()}")
    stale = subprocess.run(
        [argument for argument in command if argument != seed_flag]
        + ["--seed-opt-level=" + ("-O1" if seed_flag != "--seed-opt-level=-O1" else "-O0")],
        capture_output=True,
        text=True,
        check=False,
    )
    if stale.returncode == 0:
        fail("changing a seed flag did not invalidate the manifest")
    print("compiler manifest smoke OK: content, artifact, toolchain, ABI, and flag checks pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
