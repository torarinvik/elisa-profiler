#!/usr/bin/env python3
"""Exercise native accounting metamorphic properties and artifact round trips."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "examples" / "hot_loop.elisa"
TIMEOUT_SECONDS = 120
REPETITIONS = 3
EXPECTED_DETAIL_SUMMARIES = {
    "locations": ("detail_records", "locations"),
    "dropped_call_edges": ("dropped_call_edges", None),
    "dropped_stacks": ("dropped_stacks", None),
    "capture_bytes_dropped": ("capture_bytes_dropped", None),
    "frame_dropped": ("frame_dropped", None),
}


def run(native: Path, *arguments: str) -> None:
    process = subprocess.run(
        [str(native), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=TIMEOUT_SECONDS,
    )
    if process.returncode != 0:
        raise SystemExit(process.stderr or process.stdout)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_repetition_sums(report: dict) -> None:
    repetitions = report["run"]["repetitions"]
    if len(repetitions) != REPETITIONS:
        raise SystemExit("native report lost a repetition while aggregating")
    for summary_name, (repetition_name, detail_name) in EXPECTED_DETAIL_SUMMARIES.items():
        expected = 0
        for repetition in repetitions:
            value = repetition[repetition_name]
            if detail_name is not None:
                value = value[detail_name]
            expected += value
        actual = report["summary"][summary_name]
        if actual != expected:
            raise SystemExit(
                f"aggregate {summary_name} changed under repetition merge: "
                f"expected {expected}, got {actual}"
            )


def assert_zero_deltas(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"delta", "relative_delta_basis_points"} and nested is not None and nested != 0:
                raise SystemExit(f"self-comparison produced a nonzero {key}: {nested}")
            assert_zero_deltas(nested)
    elif isinstance(value, list):
        for nested in value:
            assert_zero_deltas(nested)


def main() -> int:
    native = Path(sys.argv[1]) if len(sys.argv) == 2 else ROOT / "bin" / "elisa-profiler"
    with tempfile.TemporaryDirectory(prefix="elisa-profiler-metamorphic-") as directory:
        work = Path(directory)
        single_output = work / "single.json"
        repeated_output = work / "repeated.json"
        run(native, "profile", str(SOURCE), "--repeat", "1", "--format", "json", "--output", str(single_output))
        run(native, "profile", str(SOURCE), "--repeat", str(REPETITIONS), "--format", "json", "--output", str(repeated_output))
        single = read_json(single_output)
        repeated = read_json(repeated_output)
        assert_repetition_sums(repeated)
        if repeated["summary"]["locations"] != single["summary"]["locations"] * REPETITIONS:
            raise SystemExit("location accounting is not repetition-linear")

        self_comparison = work / "self-comparison.json"
        run(native, "compare", str(repeated_output), str(repeated_output), "--format", "json", "--output", str(self_comparison))
        comparison = read_json(self_comparison)
        if comparison["gate"]["status"] != "not_requested":
            raise SystemExit("self-comparison unexpectedly changed gate state")
        assert_zero_deltas(comparison["functions"])
        assert_zero_deltas(comparison["call_edges"])
        assert_zero_deltas(comparison["stacks"])
        assert_zero_deltas(comparison["locations"])

        artifact_report = work / "artifact-source.json"
        artifact = work / "capture.elisaprof"
        run(native, "record", str(SOURCE), "--format", "json", "--output", str(artifact_report), "--artifact-output", str(artifact))
        round_trip = work / "artifact-round-trip.json"
        run(native, "report", str(artifact), "--format", "json", "--output", str(round_trip))
        if read_json(artifact_report)["summary"] != read_json(round_trip)["summary"]:
            raise SystemExit("artifact round trip changed the normalized summary")
    print("metamorphic accounting smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
