#!/usr/bin/env python3
"""Exercise native comparison's workload-identity warning without launching a target."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


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
        baseline.write_text(json.dumps(capture(["--alpha"])), encoding="utf-8")
        candidate.write_text(json.dumps(capture(["--beta"], exit_code=None)), encoding="utf-8")
        result = subprocess.run(
            [str(profiler), "compare", str(baseline), str(candidate), "--format", "json", "--output", str(output)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise SystemExit(f"native comparison failed: {result.stderr or result.stdout}")
        comparison = json.loads(output.read_text(encoding="utf-8"))
        schema_check = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("profile_schema_smoke.py")),
                str(Path(__file__).parents[1] / "docs/comparison.schema.json"),
                str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
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
        if comparison["candidate"]["exit_code"] is not None:
            raise SystemExit("native comparison did not preserve a signaled null exit code")
        if "baseline or candidate target execution failed" not in comparison.get("warnings", []):
            raise SystemExit("native comparison omitted the target-failure warning")

        deep = capture([])
        nested: dict[str, object] = deep["workload"]  # type: ignore[assignment]
        for _ in range(129):
            child: dict[str, object] = {}
            nested["nested"] = child
            nested = child
        deep_path = root / "deep.json"
        deep_path.write_text(json.dumps(deep), encoding="utf-8")
        rejected_depth = subprocess.run(
            [str(profiler), "compare", deep_path, deep_path, "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if rejected_depth.returncode == 0:
            raise SystemExit("native comparison accepted over-deep JSON nesting")

        overflow = capture([])
        overflow["run"]["execution_ms_mean"] = 9223372036854776  # type: ignore[index]
        overflow_path = root / "overflow.json"
        overflow_path.write_text(json.dumps(overflow), encoding="utf-8")
        rejected_overflow = subprocess.run(
            [str(profiler), "compare", overflow_path, overflow_path, "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if rejected_overflow.returncode == 0:
            raise SystemExit("native comparison accepted overflowing millisecond JSON")

        precision = capture([])
        precision["run"]["execution_ms_mean"] = 1.1234  # type: ignore[index]
        precision_path = root / "precision.json"
        precision_path.write_text(json.dumps(precision), encoding="utf-8")
        rejected_precision = subprocess.run(
            [str(profiler), "compare", precision_path, precision_path, "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
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
        rendered_large = subprocess.run(
            [str(profiler), "compare", largest_valid_path, largest_valid_path, "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
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
        rejected_control = subprocess.run(
            [str(profiler), "compare", control_path, control_path, "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if rejected_control.returncode == 0:
            raise SystemExit("native comparison accepted a raw control character in JSON")

        invalid_token_path = root / "invalid-token.json"
        invalid_token_path.write_text(
            json.dumps(capture([])).replace('"exit_code": 0', '"exit_code": nullsuffix'),
            encoding="utf-8",
        )
        rejected_token = subprocess.run(
            [str(profiler), "compare", invalid_token_path, invalid_token_path, "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if rejected_token.returncode == 0:
            raise SystemExit("native comparison accepted a suffixed JSON null token")
    print("native workload comparison smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
