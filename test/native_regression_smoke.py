#!/usr/bin/env python3
"""Exercise native report semantics and OS error paths through the public CLI."""

import copy
import json
from pathlib import Path
import subprocess
import statistics
import tempfile

ROOT = Path(__file__).resolve().parent.parent
NATIVE = ROOT / "bin" / "elisa-profiler"
TIMEOUT_SECONDS = 120
ERROR_STATUS = 2


def run(*args, ok=True, expected=None):
    result = subprocess.run(
        [str(NATIVE), *map(str, args)], capture_output=True, timeout=TIMEOUT_SECONDS
    )
    assert result.returncode == (expected if expected is not None else (0 if ok else ERROR_STATUS)), (
        args, result.returncode, result.stderr
    )
    return result.stdout


def main():
    report = {
        "schema_version": 1,
        "compiler": {"source": "nested decoy", "branch": "test", "commit": "abc"},
        "source": "café/λ/😀\n\t.elisa",
        "summary": {
            "events": 7, "locations": 2, "dropped": 0,
            "statement_events": 5, "value_events": 0, "function_events": 2,
            "thread_count": 1, "stack_overflow_entries": 0,
            "trace_events_omitted": 0, "detail_budget_exceeded": False,
        },
        "run": {
            "opt_level": "-O0", "exit_code": 0, "execution_ms_mean": 1.25,
            "compile_ms": 2.5, "location_timing": True,
        },
        "stacks": [
            {"stack": "root", "call_events": 1, "self_ns": 0},
            {"stack": "root;work", "call_events": 6, "self_ns": 123},
        ],
    }
    with tempfile.TemporaryDirectory(prefix="elisa-native-regression-") as directory:
        work = Path(directory)
        capture = work / "capture.json"
        capture.write_text(json.dumps(report), encoding="utf-8")
        comparison = json.loads(run("compare", capture, capture, "--format", "json"))
        assert comparison["baseline"]["source"] == report["source"]
        assert comparison["status"] == "ok"
        assert comparison["metrics"]["execution_ms_mean"]["baseline"] == 1.25
        report["summary"]["dropped_call_edges"] = 1
        capture.write_text(json.dumps(report))
        comparison = json.loads(run("compare", capture, capture, "--format", "json"))
        assert comparison["status"] == "warning"
        report["summary"]["dropped_call_edges"] = 0
        capture.write_text(json.dumps(report))
        folded = run("report", capture, "--format", "folded")
        assert folded == b"root;work 123\n", folded
        speedscope = json.loads(run("report", capture, "--format", "speedscope"))
        assert speedscope["profiles"][0]["unit"] == "nanoseconds"
        assert speedscope["profiles"][0]["weights"] == [123]
        report["run"]["location_timing"] = False
        capture.write_text(json.dumps(report), encoding="utf-8")
        speedscope = json.loads(run("report", capture, "--format", "speedscope"))
        assert speedscope["profiles"][0]["unit"] == "none"
        assert speedscope["profiles"][0]["weights"] == [1, 6]

        output = work / "output.txt"
        output.write_bytes(b"stale" * 10000)
        run("report", capture, "--format", "folded", "--output", output)
        assert output.read_bytes() == b"root 1\nroot;work 6\n"
        unused = work / "unused"
        run("report", capture, "--format", "html", "--format", "folded",
            "--output", unused, "--output", output)
        assert not unused.exists()
        assert output.read_bytes() == b"root 1\nroot;work 6\n"
        assert run("compare", capture, capture, "--format", "json",
                   "--format", "text").startswith(b"Elisa profile comparison")
        run("report", work / "missing", "--format", "text", ok=False)
        run("report", capture, "--format", "text", "--output", work, ok=False)

        for malformed in ('9223372036854775808', '7garbage', '07', '7.1'):
            capture.write_text(json.dumps(report).replace('"events": 7', '"events": ' + malformed))
            run("compare", capture, capture, "--format", "json", ok=False)
        for escaped in (r'\u00g0', r'\ud800', r'\udc00'):
            invalid = copy.deepcopy(report)
            invalid["source"] = "REPLACE"
            capture.write_text(json.dumps(invalid).replace("REPLACE", escaped))
            run("compare", capture, capture, "--format", "json", ok=False)
        for option in ("--repeat", "--warmup", "--max-event-trace-events"):
            for invalid in ("", "9223372036854775808"):
                run("profile", ROOT / "examples/hot_loop.elisa", option, invalid, ok=False)
        target = work / "target.elisa"
        target.write_text("def main() -> i64:\n    return 7\n")
        run("profile", target, "--format", "json", "--output", output, expected=7)
        assert json.loads(output.read_text())["run"]["exit_code"] == 7
        target.write_text('@link_name("_exit")\nextern terminate(code: i32) -> void\n\ndef main() -> i64:\n    terminate(0)\n    return 0\n')
        run("profile", target, "--format", "json", "--output", output, ok=False)
        run("profile", ROOT / "examples/hot_loop.elisa", "--repeat", "2",
            "--event-trace", "--max-event-trace-events", "10",
            "--format", "json", "--output", output)
        measured = json.loads(output.read_text())
        repetitions = measured["run"]["repetitions"]
        assert len(repetitions) == 2
        assert all(item["trace_events_captured"] == 10 for item in repetitions)
        mean_of_middle = sum(item["execution_ms"] for item in repetitions) / 2
        assert abs(measured["run"]["execution_ms_median"] - mean_of_middle) <= 0.002
        expected_stdev = statistics.pstdev(item["execution_ms"] for item in repetitions)
        assert abs(measured["run"]["execution_ms_stdev"] - expected_stdev) <= 0.002
    print("native regression smoke OK")


if __name__ == "__main__":
    main()
