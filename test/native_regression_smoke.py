#!/usr/bin/env python3
"""Exercise native report semantics and OS error paths through the public CLI."""

import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import statistics
import tempfile

ROOT = Path(__file__).resolve().parent.parent
NATIVE = ROOT / "bin" / "elisa-profiler"
TIMEOUT_SECONDS = 120
ERROR_STATUS = 2


def run(*args, ok=True, expected=None):
    process = subprocess.Popen(
        [str(NATIVE), *map(str, args)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=(os.name == "posix"),
    )
    try:
        stdout, stderr = process.communicate(timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        stdout, stderr = process.communicate()
        raise AssertionError(
            f"native regression command timed out after {TIMEOUT_SECONDS}s: {args}; "
            f"stdout={stdout[-500:]!r} stderr={stderr[-500:]!r}"
        ) from error
    result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
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
        "functions": [],
        "call_edges": [],
        "locations": [],
        "stacks": [
            {"stack": "root", "call_events": 1, "completed_calls": 1, "self_ns": 0},
            {"stack": "root;work", "call_events": 6, "completed_calls": 6, "self_ns": 123},
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
        report["source_snapshot"] = {
            "sha256": hashlib.sha256(b"embedded source").hexdigest(),
            "content": "embedded source",
        }
        capture.write_text(json.dumps(report), encoding="utf-8")
        assert run("report", capture, "--format", "text").startswith(b"Elisa profiler")
        report["source_snapshot"]["sha256"] = "0" * 64
        capture.write_text(json.dumps(report), encoding="utf-8")
        run("report", capture, "--format", "text", ok=False)
        del report["source_snapshot"]
        capture.write_text(json.dumps(report), encoding="utf-8")
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
        offline_html = run("report", capture, "--format", "html")
        assert b"<dt>Locations</dt><dd>2</dd>" in offline_html

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
        invalid_stack = copy.deepcopy(report)
        invalid_stack["stacks"][0]["stack"] = "raw\ncontrol"
        invalid_stack_json = json.dumps(invalid_stack).replace(r"raw\ncontrol", "raw\ncontrol")
        capture.write_bytes(invalid_stack_json.encode("utf-8"))
        run("report", capture, "--format", "folded", ok=False)
        invalid_function = copy.deepcopy(report)
        invalid_function["functions"] = [{
            "function": "broken",
            "call_events": 1,
            "completed_calls": 2,
            "inclusive_ns": 10,
            "self_ns": 10,
        }]
        capture.write_text(json.dumps(invalid_function), encoding="utf-8")
        run("report", capture, "--format", "folded", ok=False)
        invalid_thread = copy.deepcopy(report)
        invalid_thread["thread_loss"] = [{
            "thread_id": 0,
            "events": 1,
            "location_dropped": 0,
            "call_edge_dropped": 0,
            "stack_dropped": 0,
            "trace_dropped": 0,
            "bytes_dropped": -1,
        }]
        capture.write_text(json.dumps(invalid_thread), encoding="utf-8")
        run("report", capture, "--format", "text", ok=False)
        for option in ("--repeat", "--warmup", "--max-event-trace-events"):
            for invalid in ("", "9223372036854775808"):
                run("profile", ROOT / "examples/hot_loop.elisa", option, invalid, ok=False)
        target = work / "target.elisa"
        target.write_text("def main() -> i64:\n    return 7\n")
        run("profile", target, "--format", "json", "--output", output, expected=7)
        failed_report = json.loads(output.read_text())
        assert failed_report["run"]["exit_code"] == 7
        assert failed_report["workload"]["source_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
        assert failed_report["run"]["signal"] is None
        assert failed_report["quality"] == {
            "capture": "target_exit",
            "detail": "complete",
            "event_counts": "exact",
            "completeness": {
                "events": "exact",
                "locations": "exact",
                "functions": "exact",
                "call_edges": "exact",
                "stacks": "exact",
                "timings": "exact",
            },
            "reasons": ["target_exit"],
        }
        target.write_text('@link_name("_exit")\nextern terminate(code: i32) -> void\n\ndef main() -> i64:\n    terminate(0)\n    return 0\n')
        run("profile", target, "--format", "json", "--output", output, ok=False)
        run("profile", ROOT / "examples/crash.elisa", "--format", "json", "--output", output, expected=134)
        crash_report = json.loads(output.read_text())
        assert crash_report["run"]["signal"] == 6
        assert crash_report["summary"]["crash_signal"] == 6
        assert crash_report["quality"]["capture"] == "target_signal"
        assert "crash_marker" in crash_report["quality"]["reasons"]
        run("profile", ROOT / "examples/hot_loop.elisa", "--repeat", "2",
            "--event-trace", "--max-event-trace-events", "10",
            "--format", "json", "--output", output)
        measured = json.loads(output.read_text())
        assert measured["run"]["collection_mode"] == "full"
        assert measured["run"]["capabilities"]["event_classes"] == ["function", "statement", "value"]
        assert measured["run"]["capabilities"]["sampling"] == "unsupported"
        assert measured["run"]["capabilities"]["timing"] == "wall"
        assert measured["summary"]["capture_started"] is True
        assert measured["summary"]["capture_complete"] is True
        manifest = json.loads(Path(str(output) + ".manifest.json").read_text(encoding="utf-8"))
        assert manifest["capture_index"]["format"] == "record-framed-v1"
        assert manifest["capture_index"]["bytes"] >= manifest["capture_index"]["valid_bytes"] > 0
        assert manifest["capture_index"]["valid_frames"] > 0
        assert len(measured["workload"]["source_sha256"]) == 64
        assert all(character in "0123456789abcdef" for character in measured["workload"]["source_sha256"])
        repetitions = measured["run"]["repetitions"]
        assert len(repetitions) == 2
        assert all(
            set(item["detail_records"])
            == {"locations", "functions", "call_edges", "stacks", "thread_loss"}
            for item in repetitions
        )
        assert measured["thread_loss"]
        assert all(
            set(record)
            == {
                "thread_id",
                "events",
                "location_dropped",
                "call_edge_dropped",
                "stack_dropped",
                "trace_dropped",
                "bytes_dropped",
            }
            for record in measured["thread_loss"]
        )
        assert all(record["events"] > 0 for record in measured["thread_loss"])
        assert all(item["detail_records"]["locations"] >= item["detail_records"]["functions"] for item in repetitions)
        assert all(item["cpu_user_ms"] is not None for item in repetitions)
        assert all(item["cpu_system_ms"] is not None for item in repetitions)
        embedded_output = work / "embedded-source.json"
        run("profile", ROOT / "examples/hot_loop.elisa", "--embed-source", "--format", "json", "--output", embedded_output)
        embedded = json.loads(embedded_output.read_text(encoding="utf-8"))
        embedded_source = (ROOT / "examples/hot_loop.elisa").read_bytes()
        assert embedded["source_snapshot"]["content"] == embedded_source.decode("utf-8")
        assert embedded["source_snapshot"]["sha256"] == hashlib.sha256(embedded_source).hexdigest()
        assert all(abs(item["cpu_ms"] - item["cpu_user_ms"] - item["cpu_system_ms"]) <= 0.002 for item in repetitions)
        assert all(item["peak_rss_bytes"] is not None and item["peak_rss_bytes"] >= 0 for item in repetitions)
        assert abs(measured["run"]["cpu_user_ms"] - sum(item["cpu_user_ms"] for item in repetitions)) <= 0.002
        assert abs(measured["run"]["cpu_system_ms"] - sum(item["cpu_system_ms"] for item in repetitions)) <= 0.002
        assert abs(measured["run"]["cpu_ms"] - sum(item["cpu_ms"] for item in repetitions)) <= 0.002
        assert measured["run"]["peak_rss_bytes"] == max(item["peak_rss_bytes"] for item in repetitions)
        assert all(item["trace_events_captured"] == 10 for item in repetitions)
        mean_of_middle = sum(item["execution_ms"] for item in repetitions) / 2
        assert abs(measured["run"]["execution_ms_median"] - mean_of_middle) <= 0.002
        expected_stdev = statistics.pstdev(item["execution_ms"] for item in repetitions)
        assert abs(measured["run"]["execution_ms_stdev"] - expected_stdev) <= 0.002

        threaded_output = work / "threaded.json"
        run("profile", ROOT / "examples/threaded.elisa", "--format", "json", "--output", threaded_output)
        threaded = json.loads(threaded_output.read_text(encoding="utf-8"))
        assert threaded["summary"]["thread_count"] >= 3
        assert len(threaded["thread_loss"]) >= 3
        assert all(record["events"] > 0 for record in threaded["thread_loss"])
        assert any(function["function"] == "worker" for function in threaded["functions"])
        assert b"thread loss records: present" in run("report", threaded_output, "--format", "text")
        assert b"Thread loss" in run("report", threaded_output, "--format", "html")

        functions_capture = work / "functions.json"
        values_capture = work / "values.json"
        run("profile", ROOT / "examples/hot_loop.elisa", "--mode", "functions",
            "--format", "json", "--output", functions_capture)
        functions_report = json.loads(functions_capture.read_text())
        assert functions_report["run"]["collection_mode"] == "functions"
        assert functions_report["run"]["capabilities"]["event_classes"] == ["function"]
        assert functions_report["summary"]["statement_events"] == 0
        assert functions_report["summary"]["value_events"] == 0
        assert functions_report["summary"]["function_events"] > 0

        run("profile", ROOT / "examples/hot_loop.elisa", "--mode", "statements",
            "--format", "json", "--output", output)
        statements_report = json.loads(output.read_text())
        assert statements_report["run"]["collection_mode"] == "statements"
        assert statements_report["run"]["capabilities"]["event_classes"] == ["function", "statement"]
        assert statements_report["summary"]["statement_events"] > 0
        assert statements_report["summary"]["value_events"] == 0

        run("profile", ROOT / "examples/hot_loop.elisa", "--mode", "values",
            "--format", "json", "--output", values_capture)
        values_report = json.loads(values_capture.read_text())
        assert values_report["run"]["collection_mode"] == "values"
        assert values_report["run"]["capabilities"]["event_classes"] == ["function", "value"]
        assert values_report["summary"]["statement_events"] == 0
        assert values_report["summary"]["value_events"] > 0

        run("profile", ROOT / "examples/hot_loop.elisa", "--mode", "diagnostic",
            "--format", "json", "--output", output)
        diagnostic_report = json.loads(output.read_text())
        assert diagnostic_report["run"]["collection_mode"] == "diagnostic"
        assert diagnostic_report["run"]["event_trace_enabled"] is True
        mode_comparison = json.loads(run("compare", functions_capture, values_capture, "--format", "json"))
        assert mode_comparison["collection_mode_match"] is False
        assert any("different collection modes" in warning for warning in mode_comparison["warnings"])
        run("profile", ROOT / "examples/hot_loop.elisa", "--mode", "sampling",
            "--format", "json", "--output", output, ok=False)
    print("native regression smoke OK")


if __name__ == "__main__":
    main()
