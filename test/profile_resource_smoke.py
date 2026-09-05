#!/usr/bin/env python3
"""Verify peak-RSS parsing for BSD and GNU time output."""

from __future__ import annotations

from importlib.machinery import SourceFileLoader
import importlib.util
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parent.parent
PROFILER = ROOT / "scripts" / "elisa-profiler-legacy.py"


def load_profiler():
    loader = SourceFileLoader("elisa_profiler_resource_test", str(PROFILER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError(f"could not load profiler: {PROFILER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    profiler = load_profiler()
    with tempfile.TemporaryDirectory(prefix="elisa-profile-resource-") as directory:
        resource_path = Path(directory) / "time.txt"
        resource_path.write_text(
            "\n            123 maximum resident set size\n",
            encoding="utf-8",
        )
        assert profiler.parse_resource_report(resource_path)["peak_rss_bytes"] == 123

        resource_path.write_text(
            "Maximum resident set size (kbytes): 456\n",
            encoding="utf-8",
        )
        assert profiler.parse_resource_report(resource_path)["peak_rss_bytes"] == 456 * 1024

        resource_path.write_text("unrelated resource output\n", encoding="utf-8")
        assert profiler.parse_resource_report(resource_path) == {}
    print("profile resource smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
