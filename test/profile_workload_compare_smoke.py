#!/usr/bin/env python3
"""Exercise native comparison's workload-identity warning without launching a target."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


DEFAULT_NATIVE_COMMAND_TIMEOUT_SECONDS = 10.0
NATIVE_COMMAND_TIMEOUT_SECONDS = float(
    os.environ.get("ELISA_NATIVE_SMOKE_TIMEOUT_SECONDS", DEFAULT_NATIVE_COMMAND_TIMEOUT_SECONDS)
)


def run_command(command: list[str], label: str) -> subprocess.CompletedProcess[str]:
    """Keep a stalled native executable from hanging the entire smoke suite."""
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=NATIVE_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise SystemExit(
            f"{label} timed out after {NATIVE_COMMAND_TIMEOUT_SECONDS:g}s; "
            "inspect the native process before retrying"
        ) from error


def capture(arguments: list[str], exit_code: int | None = 0) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": "fixture.elisa",
        "compiler": {"branch": "codex/profiler", "commit": "fixture"},
        "summary": {
            "events": 1,
            "locations": 1,
            "dropped": 0,
            "stack_overflow_entries": 0,
            "thread_count": 1,
            "trace_events_omitted": 0,
            "detail_budget_exceeded": False,
        },
        "run": {
            "location_timing": True,
            "opt_level": "-O0",
            "execution_ms_mean": 1.0,
            "compile_ms": 1.0,
            "cpu_ms": 0.5,
            "peak_rss_bytes": 4096,
            "exit_code": exit_code,
        },
        "workload": {
            "source_size_bytes": 1,
            "working_directory": ".",
            "stdin": None,
            "environment_override_keys": [],
            "arguments": arguments,
        },
    }


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: profile_workload_compare_smoke.py NATIVE_PROFILER")
    profiler = Path(sys.argv[1])
    with tempfile.TemporaryDirectory(prefix="elisa-workload-compare-") as directory:
        root = Path(directory)
        baseline = root / "baseline.json"
        candidate = root / "candidate.json"
        output = root / "comparison.json"
        baseline_capture = capture(["--alpha"])
        baseline_capture["functions"] = [{
            "function": "alpha",
            "events": 7,
            "call_events": 7,
            "completed_calls": 7,
            "inclusive_ns": 700,
            "self_ns": 500,
            "interval_ns": 700,
            "max_interval_ns": 200,
        }]
        baseline_capture["call_edges"] = [{
            "caller": "root",
            "callee": "alpha",
            "call_events": 7,
            "completed_calls": 7,
            "inclusive_ns": 700,
        }]
        baseline_capture["stacks"] = [{
            "stack": "root;alpha",
            "call_events": 7,
            "completed_calls": 7,
            "self_ns": 500,
        }]
        baseline_capture["locations"] = [{
            "source": "fixture.elisa",
            "kind": "statement",
            "function": "alpha",
            "line": 10,
            "variable": None,
            "signed": False,
            "count": 7,
            "interval_ns": 700,
            "max_interval_ns": 200,
        }]
        candidate_capture = capture(["--beta"], exit_code=None)
        candidate_capture["run"]["execution_ms_mean"] = 1.5  # type: ignore[index]
        candidate_capture["run"]["cpu_ms"] = 0.75  # type: ignore[index]
        candidate_capture["run"]["peak_rss_bytes"] = 6144  # type: ignore[index]
        candidate_capture["functions"] = [{
            "function": "beta",
            "events": 9,
            "call_events": 9,
            "completed_calls": 8,
            "inclusive_ns": 900,
            "self_ns": 600,
            "interval_ns": 900,
            "max_interval_ns": 300,
        }]
        candidate_capture["call_edges"] = [{
            "caller": "root",
            "callee": "beta",
            "call_events": 9,
            "completed_calls": 8,
            "inclusive_ns": 900,
        }]
        candidate_capture["stacks"] = [{
            "stack": "root;beta",
            "call_events": 9,
            "completed_calls": 8,
            "self_ns": 600,
        }]
        candidate_capture["locations"] = [{
            "source": "fixture.elisa",
            "kind": "statement",
            "function": "beta",
            "line": 11,
            "variable": None,
            "signed": False,
            "count": 9,
            "interval_ns": 900,
            "max_interval_ns": 300,
        }]
        baseline.write_text(json.dumps(baseline_capture), encoding="utf-8")
        candidate.write_text(json.dumps(candidate_capture), encoding="utf-8")
        result = run_command(
            [str(profiler), "compare", str(baseline), str(candidate), "--format", "json", "--output", str(output)],
            "native comparison",
        )
        if result.returncode != 0:
            raise SystemExit(f"native comparison failed: {result.stderr or result.stdout}")
        comparison = json.loads(output.read_text(encoding="utf-8"))
        schema_check = run_command(
            [
                sys.executable,
                str(Path(__file__).with_name("profile_schema_smoke.py")),
                str(Path(__file__).parents[1] / "docs/profile-comparison.schema.json"),
                str(output),
            ],
            "comparison schema check",
        )
        if schema_check.returncode != 0:
            raise SystemExit(f"native comparison schema failed: {schema_check.stderr or schema_check.stdout}")
        if comparison.get("workload_metadata_match") is not False:
            raise SystemExit("native comparison did not mark workload metadata as different")
        warning = "baseline and candidate use different workload metadata"
        if warning not in comparison.get("warnings", []):
            raise SystemExit("native comparison omitted the workload warning")
        if comparison.get("status") != "warning":
            raise SystemExit("native comparison did not report warning status")
        if comparison["metrics"]["cpu_ms"]["baseline"] != 0.5:
            raise SystemExit("native comparison omitted CPU timing")
        if comparison["metrics"]["execution_ms_mean"]["relative_delta_basis_points"] != 5000:
            raise SystemExit("native comparison omitted exact wall relative delta")
        if comparison["metrics"]["cpu_ms"]["relative_delta_basis_points"] != 5000:
            raise SystemExit("native comparison omitted exact CPU relative delta")
        if comparison["metrics"]["peak_rss_bytes"]["relative_delta_basis_points"] != 5000:
            raise SystemExit("native comparison omitted exact RSS relative delta")
        if comparison["metrics"]["events"]["relative_delta_basis_points"] != 0:
            raise SystemExit("native comparison omitted exact event relative delta")
        if comparison["metrics"]["peak_rss_bytes"]["baseline"] != 4096:
            raise SystemExit("native comparison omitted peak RSS")
        if any("resource-metric availability" in warning for warning in comparison.get("warnings", [])):
            raise SystemExit("native comparison reported a false resource-availability mismatch")
        if comparison["gate"]["status"] != "not_requested":
            raise SystemExit("native comparison unexpectedly requested a threshold gate")
        if any(value is not None for value in comparison["thresholds"].values()):
            raise SystemExit("native comparison emitted an unexpected default threshold")
        html_output = root / "comparison.html"
        html_result = run_command(
            [str(profiler), "compare", str(baseline), str(candidate), "--format", "html", "--output", str(html_output)],
            "native comparison html",
        )
        if html_result.returncode != 0:
            raise SystemExit(f"native comparison html failed: {html_result.stderr or html_result.stdout}")
        html = html_output.read_bytes()
        for marker in (
            b"Elisa profile comparison",
            b"Mean execution",
            b"Workload identity",
            b"Warnings",
            b"Function identity changes",
            b"Call-edge identity changes",
            b"Stack identity changes",
            b"Source-location identity changes",
            b"@media(prefers-reduced-motion:reduce)",
            b"@media print",
            b"summary:focus-visible",
            b"absolute change first",
            b"50.00%",
            b"relative_delta_basis_points",
            b">Removed<",
            b">Added<",
            b"Raw comparison JSON",
        ):
            if marker not in html:
                raise SystemExit(f"native comparison html omitted {marker!r}")
        if b"<code>alpha</code>" not in html or b"<code>beta</code>" not in html:
            raise SystemExit("native comparison html omitted added/removed function identities")
        if b"baseline and candidate use different workload metadata" not in html:
            raise SystemExit("native comparison html omitted its workload warning")
        function_changes = {item["function"]: item for item in comparison["functions"]}
        if set(function_changes) != {"alpha", "beta"}:
            raise SystemExit("native comparison did not retain added and removed functions")
        if function_changes["alpha"]["inclusive_ns"]["candidate"] is not None:
            raise SystemExit("native comparison did not mark the removed function as unavailable")
        if function_changes["alpha"]["match"] != "removed":
            raise SystemExit("native comparison did not label the removed function")
        if function_changes["alpha"]["self_ns"]["relative_delta_basis_points"] is not None:
            raise SystemExit("native comparison did not mark an unavailable relative delta as null")
        if function_changes["beta"]["inclusive_ns"]["baseline"] is not None:
            raise SystemExit("native comparison did not mark the added function as unavailable")
        if function_changes["beta"]["match"] != "added":
            raise SystemExit("native comparison did not label the added function")
        edge_changes = {(item["caller"], item["callee"]): item for item in comparison["call_edges"]}
        if set(edge_changes) != {("root", "alpha"), ("root", "beta")}:
            raise SystemExit("native comparison did not retain added and removed call edges")
        if edge_changes[("root", "alpha")]["inclusive_ns"]["candidate"] is not None:
            raise SystemExit("native comparison did not mark the removed call edge as unavailable")
        if edge_changes[("root", "alpha")]["match"] != "removed":
            raise SystemExit("native comparison did not label the removed call edge")
        if edge_changes[("root", "beta")]["match"] != "added":
            raise SystemExit("native comparison did not label the added call edge")
        stack_changes = {item["stack"]: item for item in comparison["stacks"]}
        if set(stack_changes) != {"root;alpha", "root;beta"}:
            raise SystemExit("native comparison did not retain added and removed stacks")
        if stack_changes["root;beta"]["self_ns"]["baseline"] is not None:
            raise SystemExit("native comparison did not mark the added stack as unavailable")
        if stack_changes["root;alpha"]["match"] != "removed" or stack_changes["root;beta"]["match"] != "added":
            raise SystemExit("native comparison did not label stack additions and removals")
        location_changes = {
            (item["source"], item["kind"], item["function"], item["line"], item["variable"], item["signed"]): item
            for item in comparison["locations"]
        }
        if set(location_changes) != {
            ("fixture.elisa", "statement", "alpha", 10, None, False),
            ("fixture.elisa", "statement", "beta", 11, None, False),
        }:
            raise SystemExit("native comparison did not retain added and removed source locations")
        if location_changes[("fixture.elisa", "statement", "alpha", 10, None, False)]["count"]["candidate"] is not None:
            raise SystemExit("native comparison did not mark the removed source location as unavailable")
        if location_changes[("fixture.elisa", "statement", "beta", 11, None, False)]["count"]["baseline"] is not None:
            raise SystemExit("native comparison did not mark the added source location as unavailable")
        if location_changes[("fixture.elisa", "statement", "alpha", 10, None, False)]["match"] != "removed" or location_changes[("fixture.elisa", "statement", "beta", 11, None, False)]["match"] != "added":
            raise SystemExit("native comparison did not label source-location additions and removals")
        if comparison["candidate"]["exit_code"] is not None:
            raise SystemExit("native comparison did not preserve a signaled null exit code")
        if "baseline or candidate target execution failed" not in comparison.get("warnings", []):
            raise SystemExit("native comparison omitted the target-failure warning")

        gate_baseline = capture(["--same-input"])
        gate_baseline["functions"] = [{
            "function": "alpha",
            "events": 7,
            "call_events": 7,
            "completed_calls": 7,
            "inclusive_ns": 700,
            "self_ns": 500,
            "interval_ns": 700,
            "max_interval_ns": 200,
        }]
        gate_candidate = json.loads(json.dumps(gate_baseline))
        gate_candidate["run"]["execution_ms_mean"] = 2.0  # type: ignore[index]
        gate_baseline_path = root / "gate-baseline.json"
        gate_candidate_path = root / "gate-candidate.json"
        gate_output = root / "gate-comparison.json"
        gate_baseline_path.write_text(json.dumps(gate_baseline), encoding="utf-8")
        gate_candidate_path.write_text(json.dumps(gate_candidate), encoding="utf-8")
        gate_result = run_command(
            [
                str(profiler),
                "compare",
                gate_baseline_path,
                gate_candidate_path,
                "--format",
                "json",
                "--output",
                gate_output,
                "--max-wall-regression-percent",
                "10",
            ],
            "wall regression gate",
        )
        if gate_result.returncode != 5:
            raise SystemExit(f"wall regression gate returned {gate_result.returncode}, expected 5")
        gate_comparison = json.loads(gate_output.read_text(encoding="utf-8"))
        if gate_comparison["gate"]["status"] != "fail":
            raise SystemExit("wall regression gate did not report fail")
        if "wall_regression_percent" not in gate_comparison["gate"]["violations"]:
            raise SystemExit("wall regression gate omitted its violation")
        if gate_comparison["thresholds"]["wall_regression_percent"] != 10:
            raise SystemExit("wall regression gate omitted its threshold")

        absolute_output = root / "absolute-comparison.json"
        absolute_result = run_command(
            [
                str(profiler),
                "compare",
                gate_baseline_path,
                gate_candidate_path,
                "--format",
                "json",
                "--output",
                absolute_output,
                "--max-wall-ms",
                "1",
            ],
            "absolute wall regression gate",
        )
        if absolute_result.returncode != 5:
            raise SystemExit(f"absolute wall gate returned {absolute_result.returncode}, expected 5")
        absolute_comparison = json.loads(absolute_output.read_text(encoding="utf-8"))
        if absolute_comparison["gate"]["violations"] != ["wall_max_ms"]:
            raise SystemExit("absolute wall gate reported an unexpected violation")

        inconclusive_output = root / "inconclusive-comparison.json"
        inconclusive_result = run_command(
            [
                str(profiler),
                "compare",
                baseline,
                candidate,
                "--format",
                "json",
                "--output",
                inconclusive_output,
                "--max-wall-regression-percent",
                "10",
            ],
            "inconclusive comparison gate",
        )
        if inconclusive_result.returncode != 4:
            raise SystemExit(f"inconclusive gate returned {inconclusive_result.returncode}, expected 4")
        inconclusive_comparison = json.loads(inconclusive_output.read_text(encoding="utf-8"))
        if inconclusive_comparison["gate"]["status"] != "inconclusive":
            raise SystemExit("inconclusive gate did not preserve comparison uncertainty")

        function_gate_candidate = json.loads(json.dumps(gate_baseline))
        function_gate_candidate["functions"][0]["self_ns"] = 600  # type: ignore[index]
        function_gate_candidate_path = root / "function-gate-candidate.json"
        function_gate_output = root / "function-gate-comparison.json"
        function_gate_candidate_path.write_text(json.dumps(function_gate_candidate), encoding="utf-8")
        function_gate_result = run_command(
            [
                str(profiler),
                "compare",
                gate_baseline_path,
                function_gate_candidate_path,
                "--format",
                "json",
                "--output",
                function_gate_output,
                "--max-function-self-regression-percent",
                "10",
            ],
            "function regression gate",
        )
        if function_gate_result.returncode != 5:
            raise SystemExit(f"function regression gate returned {function_gate_result.returncode}, expected 5")
        function_gate_comparison = json.loads(function_gate_output.read_text(encoding="utf-8"))
        if function_gate_comparison["gate"]["violations"] != ["function_self_regression_percent"]:
            raise SystemExit("function regression gate reported an unexpected violation")

        maximum_count = 9223372036854775807
        extreme_baseline = capture([])
        extreme_candidate = capture([])
        for field in (
            "events",
            "locations",
            "dropped",
            "thread_count",
            "stack_overflow_entries",
            "trace_events_omitted",
        ):
            extreme_baseline["summary"][field] = maximum_count  # type: ignore[index]
            extreme_candidate["summary"][field] = 0  # type: ignore[index]
        extreme_baseline_path = root / "extreme-baseline.json"
        extreme_candidate_path = root / "extreme-candidate.json"
        extreme_output = root / "extreme-comparison.json"
        extreme_baseline_path.write_text(json.dumps(extreme_baseline), encoding="utf-8")
        extreme_candidate_path.write_text(json.dumps(extreme_candidate), encoding="utf-8")
        extreme_result = run_command(
            [
                str(profiler),
                "compare",
                extreme_baseline_path,
                extreme_candidate_path,
                "--format",
                "json",
                "--output",
                extreme_output,
            ],
            "saturated comparison delta",
        )
        if extreme_result.returncode != 0:
            raise SystemExit(f"saturated comparison failed: {extreme_result.stderr or extreme_result.stdout}")
        extreme_comparison = json.loads(extreme_output.read_text(encoding="utf-8"))
        for metric in (
            "events",
            "locations",
            "dropped_events",
            "thread_count",
            "stack_overflow_entries",
            "trace_events_omitted",
        ):
            if extreme_comparison["metrics"][metric]["delta"] != -maximum_count:
                raise SystemExit(f"comparison delta wrapped for {metric}")

        deep = capture([])
        nested: dict[str, object] = deep["workload"]  # type: ignore[assignment]
        for _ in range(129):
            child: dict[str, object] = {}
            nested["nested"] = child
            nested = child
        deep_path = root / "deep.json"
        deep_path.write_text(json.dumps(deep), encoding="utf-8")
        rejected_depth = run_command(
            [str(profiler), "compare", deep_path, deep_path, "--format", "json"],
            "over-deep JSON rejection",
        )
        if rejected_depth.returncode == 0:
            raise SystemExit("native comparison accepted over-deep JSON nesting")

        overflow = capture([])
        overflow["run"]["execution_ms_mean"] = 9223372036854776  # type: ignore[index]
        overflow_path = root / "overflow.json"
        overflow_path.write_text(json.dumps(overflow), encoding="utf-8")
        rejected_overflow = run_command(
            [str(profiler), "compare", overflow_path, overflow_path, "--format", "json"],
            "overflowing timing rejection",
        )
        if rejected_overflow.returncode == 0:
            raise SystemExit("native comparison accepted overflowing millisecond JSON")

        precision = capture([])
        precision["run"]["execution_ms_mean"] = 1.1234  # type: ignore[index]
        precision_path = root / "precision.json"
        precision_path.write_text(json.dumps(precision), encoding="utf-8")
        rejected_precision = run_command(
            [str(profiler), "compare", precision_path, precision_path, "--format", "json"],
            "excess timing precision rejection",
        )
        if rejected_precision.returncode == 0:
            raise SystemExit("native comparison silently truncated millisecond precision")

        largest_valid = capture([])
        largest_valid["run"]["execution_ms_mean"] = "__largest_valid_timing__"  # type: ignore[index]
        largest_valid_path = root / "largest-valid.json"
        largest_valid_text = json.dumps(largest_valid).replace(
            '"__largest_valid_timing__"', "9223372036854775.807"
        )
        largest_valid_path.write_text(largest_valid_text, encoding="utf-8")
        rendered_large = run_command(
            [str(profiler), "compare", largest_valid_path, largest_valid_path, "--format", "json"],
            "largest timing render",
        )
        if rendered_large.returncode != 0:
            raise SystemExit(
                "native comparison failed at the largest bounded timing value: "
                f"{rendered_large.stderr or rendered_large.stdout}"
            )

        control_path = root / "control-character.json"
        control_bytes = json.dumps(capture([])).encode("utf-8").replace(
            b"fixture.elisa", b"fixture\ninvalid"
        )
        # The literal newline is intentionally invalid JSON; it exercises the
        # native parser rather than Python's JSON writer.
        control_path.write_bytes(control_bytes)
        rejected_control = run_command(
            [str(profiler), "compare", control_path, control_path, "--format", "json"],
            "control-character JSON rejection",
        )
        if rejected_control.returncode == 0:
            raise SystemExit("native comparison accepted a raw control character in JSON")

        invalid_token_path = root / "invalid-token.json"
        invalid_token_path.write_text(
            json.dumps(capture([])).replace('"exit_code": 0', '"exit_code": nullsuffix'),
            encoding="utf-8",
        )
        rejected_token = run_command(
            [str(profiler), "compare", invalid_token_path, invalid_token_path, "--format", "json"],
            "invalid JSON token rejection",
        )
        if rejected_token.returncode == 0:
            raise SystemExit("native comparison accepted a suffixed JSON null token")
    print("native workload comparison smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
