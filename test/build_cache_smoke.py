#!/usr/bin/env python3
"""Exercise conservative Elisa-native instrumented executable caching."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str]) -> None:
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=60)
    if completed.returncode != 0:
        raise AssertionError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout={completed.stdout}\nstderr={completed.stderr}"
        )


def cache_report(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))["build_cache"]


def cache_metadata(path: Path) -> dict[str, object]:
    metadata = json.loads(path.read_text(encoding="utf-8"))
    assert metadata["cache_schema_version"] == 1
    assert metadata["kind"] == "elisa-instrumented-executable"
    assert isinstance(metadata["key"], str)
    assert isinstance(metadata["program_sha256"], str)
    return metadata


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_cache_smoke.py NATIVE_PROFILER")
    profiler = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="elisa-profiler-build-cache-") as directory:
        root = Path(directory)
        source = root / "input.elisa"
        cache = root / "cache"
        source.write_text("def main() -> i64:\n    return 0\n", encoding="utf-8")

        first = root / "first.json"
        second = root / "second.json"
        third = root / "third.json"
        common = [str(profiler), "profile", str(source), "--cache-dir", str(cache), "--format", "json"]
        run([*common, "--output", str(first)])
        run([*common, "--output", str(second)])

        first_cache = cache_report(first)
        second_cache = cache_report(second)
        assert first_cache["enabled"] is True
        assert first_cache["status"] == "miss"
        assert second_cache["status"] == "hit"
        assert first_cache["key"] == second_cache["key"]
        entries = list(cache.iterdir())
        assert len(entries) == 2, entries
        assert {entry.suffix for entry in entries} == {".json", ".program"}
        metadata = cache_metadata(next(entry for entry in entries if entry.suffix == ".json"))
        assert metadata["key"] == first_cache["key"]

        program_entry = next(entry for entry in entries if entry.suffix == ".program")
        program_entry.write_bytes(b"corrupt cache payload")
        repaired = root / "repaired.json"
        run([*common, "--output", str(repaired)])
        repaired_cache = cache_report(repaired)
        assert repaired_cache["status"] == "miss"
        assert repaired_cache["key"] == first_cache["key"]

        source.write_bytes(source.read_bytes() + b"\n")
        run([*common, "--output", str(third)])
        third_cache = cache_report(third)
        assert third_cache["status"] == "miss"
        assert third_cache["key"] != first_cache["key"]
        assert len(list(cache.iterdir())) == 4

    print("build cache smoke OK: miss, validated hit, and dependency invalidation pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
