#!/usr/bin/env python3
"""Verify that failed repetitions do not skew successful-run aggregates."""

from __future__ import annotations

from importlib.machinery import SourceFileLoader
import importlib.util
import json
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parent.parent
PROFILER = ROOT / "scripts" / "elisa-profiler-legacy.py"


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
        call_edges = [
            {
                "caller": "main",
                "callee": "frequent",
                "call_events": 100,
                "completed_calls": 100,
                "inclusive_ns": 100,
            },
            {
                "caller": "main",
                "callee": "hot",
                "call_events": 1,
                "completed_calls": 1,
                "inclusive_ns": 1_000,
            },
        ]
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
            call_edges,
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
        assert run["measurement_repetitions"] == 1
        assert run["measurement_basis"] == "successful"
        assert run["execution_ms"] == 10.0
        assert run["execution_ms_mean"] == 10.0
        assert run["cpu_ms"] == 5.0
        assert run["peak_rss_bytes"] == 1000
        assert report["summary"]["events"] == 2
        assert report["locations"][0]["interval_ns"] == 400
        assert [edge["callee"] for edge in report["call_edges"]] == ["hot", "frequent"]

        count_only_report = profiler.build_report(
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
            call_edges,
            [],
            exit_code=0,
            signal=None,
            run_records=[dict(run_records[0], requested_repetitions=1)],
            warmup_ms=0.0,
            warmup_repetitions=0,
            timeout_s=None,
            location_timing=False,
            opt_level="-O0",
            compile_ms=1.0,
            program_stderr="",
            temp_root=None,
            recent_events=[],
            active_stack=None,
        )
        assert [edge["callee"] for edge in count_only_report["call_edges"]] == [
            "frequent", "hot"
        ]

        count_profile = {
            "source": "count-only.elisa",
            "run": {"location_timing": False},
            "stacks": [{"stack": "main;worker", "call_events": 3, "self_ns": 0}],
        }
        speedscope = json.loads(profiler.speedscope_report(count_profile))
        assert speedscope["profiles"][0]["unit"] == "none"
        assert speedscope["profiles"][0]["weights"] == [3]
    print("profile aggregation smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
