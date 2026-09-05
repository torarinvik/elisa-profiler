#!/usr/bin/env python3
"""Verify include-aware source mapping preserves repeated includes and line endings."""

from __future__ import annotations

from importlib.machinery import SourceFileLoader
import importlib.util
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parent.parent
PROFILER = ROOT / "scripts" / "elisa-profiler-legacy.py"


def load_profiler():
    loader = SourceFileLoader("elisa_profiler_source_mapping_test", str(PROFILER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError(f"could not load profiler: {PROFILER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    profiler = load_profiler()
    with tempfile.TemporaryDirectory(prefix="elisa-profile-mapping-") as directory:
        root = Path(directory)
        helper = root / "helper.elisa"
        source = root / "main.elisa"
        helper.write_text("helper line 1\r\nhelper line 2\r\n", encoding="utf-8")
        source.write_text(
            'include "helper.elisa"\nroot line\ninclude "helper.elisa"\n',
            encoding="utf-8",
        )

        mapped = profiler.source_line_map(source)
        assert mapped == [
            (helper.resolve(), 1, "helper line 1"),
            (helper.resolve(), 2, "helper line 2"),
            (source.resolve(), 2, "root line"),
            (helper.resolve(), 1, "helper line 1"),
            (helper.resolve(), 2, "helper line 2"),
        ], mapped

        cycle_a = root / "cycle_a.elisa"
        cycle_b = root / "cycle_b.elisa"
        cycle_a.write_text('include "cycle_b.elisa"\n', encoding="utf-8")
        cycle_b.write_text('include "cycle_a.elisa"\n', encoding="utf-8")
        try:
            profiler.source_line_map(cycle_a)
        except profiler.ProfilerError as error:
            assert "cyclic include" in str(error)
        else:
            raise AssertionError("cyclic include was not rejected")
    print("source mapping smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
