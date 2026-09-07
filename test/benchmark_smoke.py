#!/usr/bin/env python3
"""Exercise the Elisa-native benchmark manifest workflow."""

import json
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent.parent
NATIVE = ROOT / "bin" / "elisa-profiler"


def main() -> None:
    manifest = ROOT / "examples" / "benchmark_pipeline.json"
    schema_check = subprocess.run(
        [
            "python3", str(ROOT / "test" / "profile_schema_smoke.py"),
            str(ROOT / "docs" / "benchmark.schema.json"), str(manifest),
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert schema_check.returncode == 0, (schema_check.stdout, schema_check.stderr)
    with tempfile.TemporaryDirectory(prefix="elisa-benchmark-") as directory:
        output = Path(directory) / "comparison.json"
        process = subprocess.run(
            [
                str(NATIVE), "benchmark", str(manifest),
                "--format", "json", "--output", str(output),
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            check=False,
        )
        assert process.returncode == 0, (process.returncode, process.stdout, process.stderr)
        comparison = json.loads(output.read_text(encoding="utf-8"))
        comparison_schema_check = subprocess.run(
            [
                "python3", str(ROOT / "test" / "profile_schema_smoke.py"),
                str(ROOT / "docs" / "profile-comparison.schema.json"), str(output),
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        assert comparison_schema_check.returncode == 0, (
            comparison_schema_check.stdout, comparison_schema_check.stderr,
        )
        assert comparison["status"] == "ok", comparison
        assert comparison["execution_order"] == "baseline_first", comparison
        assert comparison["baseline"]["source"].endswith("multi_module_pipeline.elisa")
        assert comparison["candidate"]["source"].endswith("multi_module_pipeline.elisa")
        assert comparison["metrics"]["execution_ms_mean"]["baseline"] is not None
        assert comparison["metrics"]["execution_ms_mean"]["candidate"] is not None
        assert comparison["thresholds"]["wall_regression_percent"] == 1000
        assert {row["repetition"] for row in comparison["functions"]} == {1, 2}
        assert not Path(f"{output}.baseline.json").exists()
        assert not Path(f"{output}.candidate.json").exists()
        assert not Path(f"{output}.baseline.json.manifest.json").exists()
        assert not Path(f"{output}.candidate.json.manifest.json").exists()

        ordered_manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        ordered_manifest_payload["repetitions"] = 1
        ordered_manifest_payload["warmups"] = 0
        ordered_manifest_payload["execution_order"] = "candidate_first"
        candidate_first_manifest = Path(directory) / "candidate-first.json"
        candidate_first_manifest.write_text(json.dumps(ordered_manifest_payload), encoding="utf-8")
        candidate_first_output = Path(directory) / "candidate-first-comparison.json"
        candidate_first = subprocess.run(
            [
                str(NATIVE), "benchmark", str(candidate_first_manifest),
                "--format", "json", "--output", str(candidate_first_output),
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            check=False,
        )
        assert candidate_first.returncode == 0, (candidate_first.returncode, candidate_first.stdout, candidate_first.stderr)
        assert json.loads(candidate_first_output.read_text(encoding="utf-8"))["execution_order"] == "candidate_first"

        ordered_manifest_payload["execution_order"] = "randomized"
        randomized_manifest = Path(directory) / "randomized.json"
        randomized_manifest.write_text(json.dumps(ordered_manifest_payload), encoding="utf-8")
        randomized_outputs = [Path(directory) / "randomized-one.json", Path(directory) / "randomized-two.json"]
        randomized_orders = []
        for randomized_output in randomized_outputs:
            randomized = subprocess.run(
                [
                    str(NATIVE), "benchmark", str(randomized_manifest),
                    "--format", "json", "--output", str(randomized_output),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
                check=False,
            )
            assert randomized.returncode == 0, (randomized.returncode, randomized.stdout, randomized.stderr)
            randomized_orders.append(json.loads(randomized_output.read_text(encoding="utf-8"))["execution_order"])
        assert randomized_orders[0] == randomized_orders[1]
        assert randomized_orders[0] in {"randomized_baseline_first", "randomized_candidate_first"}

        collision = Path(directory) / "collision.json"
        collision_baseline = Path(f"{collision}.baseline.json")
        collision_baseline.write_text("sentinel", encoding="utf-8")
        rejected = subprocess.run(
            [
                str(NATIVE), "benchmark", str(manifest),
                "--format", "json", "--output", str(collision),
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            check=False,
        )
        assert rejected.returncode == 2, rejected
        assert collision_baseline.read_text(encoding="utf-8") == "sentinel"


if __name__ == "__main__":
    main()
    print("benchmark smoke OK")
