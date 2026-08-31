#!/usr/bin/env python3
"""Verify that failed repetitions do not skew successful-run aggregates."""

from __future__ import annotations

from importlib.machinery import SourceFileLoader
import importlib.util
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parent.parent
PROFILER = ROOT / "scripts" / "elisa-profiler"


def load_profiler():
    loader = SourceFileLoader("elisa_profiler", str(PROFILER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError(f"could not load profiler: {PROFILER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    profiler = load_profiler()
    with tempfile.TemporaryDirectory(prefix="elisa-profile-aggregation-") as directory:
        source = Path(directory) / "demo.elisa"
        source.write_text("def main() -> i64:\n    return 0\n", encoding="utf-8")
        location = {
            "kind": "statement",
            "function": "main",
            "line": 2,
            "count": 2,
            "interval_ns": 400,
            "max_interval_ns": 300,
        }
        run_records = [
            {
                "exit_code": 0,
                "signal": None,
                "timed_out": False,
                "execution_ms": 10.0,
                "cpu_user_ms": 3.0,
                "cpu_system_ms": 2.0,
                "peak_rss_bytes": 1000,
                "requested_repetitions": 2,
            },
            {
                "exit_code": None,
                "signal": 15,
                "timed_out": True,
                "execution_ms": 2000.0,
                "cpu_user_ms": 900.0,
                "cpu_system_ms": 100.0,
                "peak_rss_bytes": 9000,
                "requested_repetitions": 2,
            },
        ]
        report = profiler.build_report(
            source,
            {"commit": "test"},
            {
                "events": 2,
                "locations": 1,
                "dropped": 0,
                "max_stack_depth": 1,
                "stack_overflow_entries": 0,
                "thread_count": 1,
            },
            [location],
            [],
            [],
            exit_code=None,
            signal=15,
            run_records=run_records,
            warmup_ms=0.0,
            warmup_repetitions=0,
            timeout_s=2.0,
            location_timing=True,
            opt_level="-O0",
            compile_ms=1.0,
            program_stderr="",
            temp_root=None,
            recent_events=[],
            active_stack=None,
        )

        run = report["run"]
        assert run["successful_repetitions"] == 1
        assert run["failed_repetitions"] == 1
        assert run["execution_ms"] == 10.0
        assert run["execution_ms_mean"] == 10.0
        assert run["cpu_ms"] == 5.0
        assert run["peak_rss_bytes"] == 1000
        assert report["summary"]["events"] == 2
        assert report["locations"][0]["interval_ns"] == 400
    print("profile aggregation smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
