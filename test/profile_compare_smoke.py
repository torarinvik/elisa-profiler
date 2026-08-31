#!/usr/bin/env python3
"""Exercise deterministic profile comparison and regression reporting."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
PROFILER = ROOT / "scripts" / "elisa-profiler"


def assert_invalid_timeout() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(PROFILER),
            "profile",
            str(ROOT / "examples" / "hello.elisa"),
            "--timeout",
            "nan",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--timeout must be a finite positive number" in result.stderr


def profile(
    execution_ms: float,
    inclusive_ns: int,
    opt_level: str,
    *,
    location_timing: bool = True,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": "demo.elisa",
        "compiler": {"commit": f"compiler-{opt_level}"},
        "summary": {"events": 100, "dropped": 0, "stack_overflow_entries": 0},
        "source_mapping": {},
        "run": {
            "exit_code": 0,
            "signal": None,
            "location_timing": location_timing,
            "timing_clock": "wall" if location_timing else None,
            "opt_level": opt_level,
            "execution_ms_mean": execution_ms,
            "compile_ms": 1.0,
            "cpu_ms": 5.0,
            "peak_rss_bytes": 1024,
            "completed_repetitions": 1,
            "successful_repetitions": 1,
            "failed_repetitions": 0,
            "measurement_basis": "successful",
            "repetitions": [{"timed_out": False}],
        },
        "functions": [
            {
                "function": "main",
                "events": 100,
                "call_events": 1,
                "completed_calls": 1,
                "inclusive_ns": inclusive_ns,
                "self_ns": inclusive_ns if location_timing else 0,
                "interval_ns": 0,
                "max_interval_ns": 0,
            }
        ],
        "call_edges": [
            {
                "caller": "main",
                "callee": "worker",
                "call_events": 1,
                "completed_calls": 1,
                "inclusive_ns": inclusive_ns,
            }
        ],
        "stacks": [
            {
                "stack": "main;worker",
                "call_events": 1 if opt_level == "-O0" else 2,
                "completed_calls": 1 if opt_level == "-O0" else 2,
                "self_ns": inclusive_ns,
            }
        ],
        "locations": [
            {
                "source": "demo.elisa",
                "line": 3,
                "function": "main",
                "kind": "statement",
                "variable": None,
                "signed": False,
                "count": 10 if opt_level == "-O0" else 20,
                "interval_ns": 0 if opt_level == "-O0" else 2_000,
                "max_interval_ns": 0 if opt_level == "-O0" else 2_000,
            }
        ],
    }


def main() -> int:
    assert_invalid_timeout()
    with tempfile.TemporaryDirectory(prefix="elisa-profile-compare-") as directory:
        root = Path(directory)
        baseline_path = root / "baseline.json"
        candidate_path = root / "candidate.json"
        comparison_path = root / "comparison.json"
        baseline_path.write_text(json.dumps(profile(10.0, 1_000, "-O0")), encoding="utf-8")
        candidate_path.write_text(json.dumps(profile(20.0, 2_000, "-O2")), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(PROFILER),
                "compare",
                str(baseline_path),
                str(candidate_path),
                "--format",
                "json",
                "--output",
                str(comparison_path),
                "--threshold",
                "10",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
        assert comparison["status"] == "regression"
        assert comparison["metrics"]["execution_ms_mean"]["percent"] == 100.0
        assert comparison["metrics"]["compile_ms"]["percent"] == 0.0
        assert any("compiler commits" in warning for warning in comparison["warnings"])
        assert not any("successful repetition counts" in warning for warning in comparison["warnings"])
        assert not any("measurement bases" in warning for warning in comparison["warnings"])
        assert any(item["scope"] == "function" for item in comparison["regressions"])
        assert any(item["scope"] == "location" for item in comparison["regressions"])
        assert any(item["scope"] == "call_edge" for item in comparison["regressions"])
        assert any(item["scope"] == "stack" for item in comparison["regressions"])
        assert comparison["call_edges"][0]["inclusive_ns"]["percent"] == 100.0
        assert comparison["stacks"][0]["self_ns"]["percent"] == 100.0
        assert comparison["metrics"]["dropped_events"] == {
            "baseline": 0,
            "candidate": 0,
            "delta": 0,
            "percent": 0.0,
        }
        assert comparison["locations"][0]["line"] == 3
        assert comparison["locations"][0]["interval_ns"]["percent"] is None
        assert any("became non-zero" in item["message"] for item in comparison["regressions"])

        different_clock_candidate = profile(10.0, 1_000, "-O0")
        different_clock_candidate["run"]["timing_clock"] = "cpu"
        different_clock_path = root / "different-clock-candidate.json"
        different_clock_comparison_path = root / "different-clock-comparison.json"
        different_clock_path.write_text(
            json.dumps(different_clock_candidate), encoding="utf-8"
        )
        different_clock_result = subprocess.run(
            [
                sys.executable,
                str(PROFILER),
                "compare",
                str(baseline_path),
                str(different_clock_path),
                "--format",
                "json",
                "--output",
                str(different_clock_comparison_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert different_clock_result.returncode == 0, different_clock_result.stderr
        different_clock_comparison = json.loads(
            different_clock_comparison_path.read_text(encoding="utf-8")
        )
        assert "baseline and candidate use different timing clocks" in different_clock_comparison[
            "warnings"
        ]

        count_baseline = profile(10.0, 0, "-O0", location_timing=False)
        count_candidate = profile(10.0, 0, "-O0", location_timing=False)
        count_candidate["stacks"][0]["call_events"] = 2
        count_candidate["stacks"][0]["completed_calls"] = 2
        count_baseline_path = root / "count-baseline.json"
        count_candidate_path = root / "count-candidate.json"
        count_comparison_path = root / "count-comparison.json"
        count_baseline_path.write_text(json.dumps(count_baseline), encoding="utf-8")
        count_candidate_path.write_text(json.dumps(count_candidate), encoding="utf-8")
        count_result = subprocess.run(
            [
                sys.executable,
                str(PROFILER),
                "compare",
                str(count_baseline_path),
                str(count_candidate_path),
                "--format",
                "json",
                "--output",
                str(count_comparison_path),
                "--threshold",
                "10",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert count_result.returncode == 0, count_result.stderr
        count_comparison = json.loads(count_comparison_path.read_text(encoding="utf-8"))
        assert any(
            item["scope"] == "stack" and item["metric"] == "call_events"
            for item in count_comparison["regressions"]
        )

        incomplete_candidate = profile(10.0, 1_000, "-O0")
        incomplete_candidate["summary"]["dropped"] = 3
        incomplete_candidate["summary"]["stack_overflow_entries"] = 1
        incomplete_path = root / "incomplete-candidate.json"
        incomplete_comparison_path = root / "incomplete-comparison.json"
        incomplete_path.write_text(json.dumps(incomplete_candidate), encoding="utf-8")
        incomplete_result = subprocess.run(
            [
                sys.executable,
                str(PROFILER),
                "compare",
                str(baseline_path),
                str(incomplete_path),
                "--format",
                "json",
                "--output",
                str(incomplete_comparison_path),
                "--fail-on-regression",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert incomplete_result.returncode == 1, incomplete_result.stderr
        incomplete_comparison = json.loads(
            incomplete_comparison_path.read_text(encoding="utf-8")
        )
        assert any(
            item["scope"] == "quality" and item["metric"] == "dropped_events"
            for item in incomplete_comparison["regressions"]
        )
        assert any(
            item["scope"] == "quality" and item["metric"] == "stack_overflow_entries"
            for item in incomplete_comparison["regressions"]
        )
        assert any("dropped trace events" in warning for warning in incomplete_comparison["warnings"])
        assert any("call-stack overflow entries" in warning for warning in incomplete_comparison["warnings"])

        baseline_without_edge = profile(10.0, 1_000, "-O0")
        baseline_without_edge["call_edges"] = []
        baseline_without_edge_path = root / "baseline-without-edge.json"
        baseline_without_edge_path.write_text(
            json.dumps(baseline_without_edge), encoding="utf-8"
        )
        new_edge_comparison_path = root / "new-edge-comparison.json"
        new_edge = subprocess.run(
            [
                sys.executable,
                str(PROFILER),
                "compare",
                str(baseline_without_edge_path),
                str(candidate_path),
                "--format",
                "json",
                "--output",
                str(new_edge_comparison_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert new_edge.returncode == 0, new_edge.stderr
        new_edge_comparison = json.loads(
            new_edge_comparison_path.read_text(encoding="utf-8")
        )
        assert new_edge_comparison["call_edges"][0]["inclusive_ns"]["baseline"] is None
        assert any(
            item["scope"] == "call_edge" and "became non-zero" in item["message"]
            for item in new_edge_comparison["regressions"]
        )

        candidate_with_different_sample_count = profile(20.0, 2_000, "-O2")
        candidate_with_different_sample_count["run"]["successful_repetitions"] = 0
        candidate_with_different_sample_count["run"]["failed_repetitions"] = 2
        candidate_with_different_sample_count["run"]["measurement_basis"] = "all_completed"
        candidate_with_different_sample_count["run"]["completed_repetitions"] = 2
        candidate_with_different_sample_count["run"]["repetitions"] = [
            {"timed_out": True},
            {"timed_out": True},
        ]
        different_sample_path = root / "different-sample-count.json"
        different_sample_path.write_text(
            json.dumps(candidate_with_different_sample_count), encoding="utf-8"
        )
        different_sample_comparison_path = root / "different-sample-comparison.json"
        different_sample = subprocess.run(
            [
                sys.executable,
                str(PROFILER),
                "compare",
                str(baseline_path),
                str(different_sample_path),
                "--format",
                "json",
                "--output",
                str(different_sample_comparison_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert different_sample.returncode == 0, different_sample.stderr
        different_sample_comparison = json.loads(
            different_sample_comparison_path.read_text(encoding="utf-8")
        )
        assert any(
            "successful repetition counts" in warning
            for warning in different_sample_comparison["warnings"]
        )
        assert any(
            "measurement bases" in warning
            for warning in different_sample_comparison["warnings"]
        )

        failing = subprocess.run(
            [
                sys.executable,
                str(PROFILER),
                "compare",
                str(baseline_path),
                str(candidate_path),
                "--threshold",
                "10",
                "--fail-on-regression",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert failing.returncode == 1, failing.stdout + failing.stderr

        failed_baseline = profile(10.0, 1_000, "-O0")
        failed_baseline["run"]["exit_code"] = 134
        failed_baseline_path = root / "failed-baseline.json"
        failed_baseline_path.write_text(json.dumps(failed_baseline), encoding="utf-8")
        rejected = subprocess.run(
            [
                sys.executable,
                str(PROFILER),
                "compare",
                str(failed_baseline_path),
                str(candidate_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert rejected.returncode == 2
        assert "baseline profile did not complete successfully" in rejected.stderr

        invalid_metric = profile(20.0, 2_000, "-O2")
        invalid_metric["functions"][0]["inclusive_ns"] = "slow"
        invalid_metric_path = root / "invalid-metric.json"
        invalid_metric_path.write_text(json.dumps(invalid_metric), encoding="utf-8")
        invalid_metric_result = subprocess.run(
            [
                sys.executable,
                str(PROFILER),
                "compare",
                str(baseline_path),
                str(invalid_metric_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert invalid_metric_result.returncode == 2
        assert "functions[0].inclusive_ns must be a finite number or null" in invalid_metric_result.stderr

        invalid_stack = profile(20.0, 2_000, "-O2")
        invalid_stack["stacks"][0]["self_ns"] = "slow"
        invalid_stack_path = root / "invalid-stack.json"
        invalid_stack_path.write_text(json.dumps(invalid_stack), encoding="utf-8")
        invalid_stack_result = subprocess.run(
            [
                sys.executable,
                str(PROFILER),
                "compare",
                str(baseline_path),
                str(invalid_stack_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert invalid_stack_result.returncode == 2
        assert "stacks[0].self_ns must be a finite number or null" in invalid_stack_result.stderr

        nonfinite_path = root / "nonfinite.json"
        nonfinite_path.write_text('{"schema_version": 1, "value": NaN}\n', encoding="utf-8")
        nonfinite_result = subprocess.run(
            [
                sys.executable,
                str(PROFILER),
                "compare",
                str(baseline_path),
                str(nonfinite_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert nonfinite_result.returncode == 2
        assert "non-finite JSON number NaN" in nonfinite_result.stderr

        malformed_path = root / "malformed.json"
        malformed_path.write_text(json.dumps({"schema_version": 1, "run": {}}), encoding="utf-8")
        malformed = subprocess.run(
            [
                sys.executable,
                str(PROFILER),
                "compare",
                str(malformed_path),
                str(candidate_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert malformed.returncode == 2
        assert "missing required sections" in malformed.stderr
    print("profile compare smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
