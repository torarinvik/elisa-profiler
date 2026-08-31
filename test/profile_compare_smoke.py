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


def profile(execution_ms: float, inclusive_ns: int, opt_level: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": "demo.elisa",
        "compiler": {"commit": f"compiler-{opt_level}"},
        "summary": {"events": 100},
        "source_mapping": {},
        "run": {
            "exit_code": 0,
            "signal": None,
            "opt_level": opt_level,
            "execution_ms_mean": execution_ms,
            "compile_ms": 1.0,
            "cpu_ms": 5.0,
            "peak_rss_bytes": 1024,
            "completed_repetitions": 1,
            "repetitions": [{"timed_out": False}],
        },
        "functions": [
            {
                "function": "main",
                "events": 100,
                "call_events": 1,
                "completed_calls": 1,
                "inclusive_ns": inclusive_ns,
                "self_ns": inclusive_ns,
                "interval_ns": 0,
                "max_interval_ns": 0,
            }
        ],
        "call_edges": [],
        "stacks": [],
        "locations": [
            {
                "source": "demo.elisa",
                "line": 3,
                "function": "main",
                "kind": "statement",
                "variable": None,
                "signed": False,
                "count": 10 if opt_level == "-O0" else 20,
                "interval_ns": 1_000 if opt_level == "-O0" else 2_000,
                "max_interval_ns": 1_000 if opt_level == "-O0" else 2_000,
            }
        ],
    }


def main() -> int:
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
        assert any(item["scope"] == "function" for item in comparison["regressions"])
        assert any(item["scope"] == "location" for item in comparison["regressions"])
        assert comparison["locations"][0]["line"] == 3

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
