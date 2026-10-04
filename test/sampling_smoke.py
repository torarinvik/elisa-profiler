#!/usr/bin/env python3
"""Exercise Elisa's launch-mode CPU sampling end to end."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SAMPLE_PERIOD_MICROSECONDS = "1000"
NON_DEFAULT_SAMPLE_PERIOD_MICROSECONDS = "2000"


def run(command: list[str]) -> None:
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=45)
    if completed.returncode != 0:
        raise AssertionError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout={completed.stdout}\nstderr={completed.stderr}"
        )


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: sampling_smoke.py NATIVE_PROFILER")
    profiler = Path(sys.argv[1]).resolve()
    source = profiler.parent.parent / "examples" / "sampling.elisa"
    with tempfile.TemporaryDirectory(prefix="elisa-profiler-sampling-") as directory:
        root = Path(directory)
        report_path = root / "sampling.json"
        non_default_report_path = root / "sampling-non-default.json"
        run([
            str(profiler),
            "profile",
            str(source),
            "--mode",
            "sample",
            "--sample-period-us",
            SAMPLE_PERIOD_MICROSECONDS,
            "--format",
            "json",
            "--output",
            str(report_path),
        ])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        manifest = json.loads(Path(f"{report_path}.manifest.json").read_text(encoding="utf-8"))
        summary = report["summary"]
        run_data = report["run"]
        capabilities = run_data["capabilities"]
        assert run_data["collection_mode"] == "sample"
        assert capabilities["event_classes"] == ["sample"]
        assert capabilities["sampling"] == "instrumented_cpu"
        assert capabilities["sampling_detail"] == {
            "status": "active",
            "reason": "sigprof_itimer_prof",
            "scope": "instrumented_call_stack",
        }
        assert summary["sample_period_microseconds"] == int(SAMPLE_PERIOD_MICROSECONDS)
        assert summary["sampling_setup_failed"] == 0
        assert summary["sample_count"] > 0
        assert summary["sample_missed"] >= 0
        assert manifest["collection_mode"] == "sample"
        assert manifest["sample_period_microseconds"] == int(SAMPLE_PERIOD_MICROSECONDS)
        assert manifest["sample_count"] == summary["sample_count"]
        assert len(report["samples"]) == summary["sample_count"]
        assert all(sample["stack"] for sample in report["samples"])
        assert all(sample["depth"] >= 1 for sample in report["samples"])
        assert all("stack_ids" in sample for sample in report["samples"])
        assert all(len(sample["stack_ids"].split(";")) == sample["depth"] for sample in report["samples"])
        assert all(all(frame_id.isdecimal() for frame_id in sample["stack_ids"].split(";"))
                   for sample in report["samples"])
        assert run_data["capabilities"]["identity"]["status"] == "compiler_stable_ids"
        malformed_ids = copy.deepcopy(report)
        sample = malformed_ids["samples"][0]
        sample["stack_ids"] = "0" if sample["depth"] != 1 else "0;1"
        malformed_ids_path = root / "sampling-malformed-ids.json"
        malformed_ids_path.write_text(json.dumps(malformed_ids), encoding="utf-8")
        rejected = subprocess.run(
            [str(profiler), "compare", str(malformed_ids_path), str(report_path), "--format", "json"],
            check=False, capture_output=True, text=True, timeout=45,
        )
        assert rejected.returncode == 2, (rejected.returncode, rejected.stdout, rejected.stderr)
        assert "malformed_profile" in rejected.stdout
        identity_source = root / "duplicate-function-names.elisa"
        identity_source.write_text(
            "module Left:\n"
            "    public:\n"
            "        def same(limit: i64) -> i64:\n"
            "            index: mutable i64 = 0\n"
            "            while index < limit |index|:\n"
            "                index <- index + 1\n"
            "            return index\n\n"
            "module Right:\n"
            "    public:\n"
            "        def same(limit: i64) -> i64:\n"
            "            index: mutable i64 = 0\n"
            "            while index < limit |index|:\n"
            "                index <- index + 1\n"
            "            return index\n\n"
            "def main() -> i64:\n"
            "    left: i64 = Left::same(25000000)\n"
            "    right: i64 = Right::same(25000000)\n"
            "    return 0 if left == right else 1\n",
            encoding="utf-8",
        )
        identity_report_path = root / "duplicate-function-names.json"
        run([
            str(profiler), "profile", str(identity_source), "--mode", "sample",
            "--sample-period-us", SAMPLE_PERIOD_MICROSECONDS, "--format", "json",
            "--output", str(identity_report_path),
        ])
        identity_report = json.loads(identity_report_path.read_text(encoding="utf-8"))
        assert all(
            "stack_ids" in item and len(item["stack_ids"].split(";")) == item["depth"]
            for item in identity_report["samples"] if item["depth"] > 0
        )
        repeated_name_ids = {
            identity
            for item in identity_report["samples"]
            for name, identity in zip(
                item["stack"].split(";"), item.get("stack_ids", "").split(";")
            )
            if name == "same"
        }
        assert len(repeated_name_ids) >= 2, (repeated_name_ids, identity_report["samples"][:4])
        speedscope_path = root / "sampling.speedscope.json"
        run([str(profiler), "report", str(report_path), "--format", "speedscope", "--output", str(speedscope_path)])
        speedscope = json.loads(speedscope_path.read_text(encoding="utf-8"))
        sampled_profile = speedscope["profiles"][0]
        assert sampled_profile["unit"] == "samples"
        assert sampled_profile["endValue"] == summary["sample_count"]
        assert len(sampled_profile["samples"]) == summary["sample_count"]
        run([
            str(profiler),
            "profile",
            str(source),
            "--mode",
            "sample",
            "--sample-period-us",
            NON_DEFAULT_SAMPLE_PERIOD_MICROSECONDS,
            "--format",
            "json",
            "--output",
            str(non_default_report_path),
        ])
        non_default_report = json.loads(non_default_report_path.read_text(encoding="utf-8"))
        assert non_default_report["summary"]["sample_period_microseconds"] == int(NON_DEFAULT_SAMPLE_PERIOD_MICROSECONDS)
        comparison_path = root / "sampling-comparison.json"
        run([
            str(profiler),
            "compare",
            str(report_path),
            str(non_default_report_path),
            "--format",
            "json",
            "--output",
            str(comparison_path),
        ])
        comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
        assert comparison["sampling_configuration_match"] is False
        assert any("sample periods" in warning for warning in comparison["warnings"])
    print("native sampling smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
