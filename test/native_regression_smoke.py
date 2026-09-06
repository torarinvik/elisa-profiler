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
INCONCLUSIVE_STATUS = 4
RECURSIVE_CALLS = 7
I64_MAX = 9223372036854775807
IDENTITY_ID_BASELINE = 2**63
IDENTITY_ID_CANDIDATE = 2**64 - 1
IDENTITY_CONTRACT_LEGACY_VERSION = 1
IDENTITY_CONTRACT_CURRENT_VERSION = 2


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
        "host": {
            "os": "Darwin", "architecture": "arm64",
            "load_average_1m": 1.234, "load_average_source": "getloadavg",
            "affinity": {"policy": "inherited", "changed": False},
            "power_thermal": None,
        },
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
        identity_function = {
            "function": "same_readable_name",
            "identity_id": IDENTITY_ID_BASELINE,
            "events": 1,
            "call_events": 1,
            "completed_calls": 1,
            "inclusive_ns": 10,
            "self_ns": 10,
            "interval_ns": 10,
            "max_interval_ns": 10,
        }
        identity_baseline = copy.deepcopy(report)
        identity_candidate = copy.deepcopy(report)
        identity_baseline["functions"] = [identity_function]
        identity_candidate["functions"] = [dict(identity_function, identity_id=IDENTITY_ID_CANDIDATE)]
        identity_baseline_path = work / "identity-baseline.json"
        identity_candidate_path = work / "identity-candidate.json"
        identity_baseline_path.write_text(json.dumps(identity_baseline), encoding="utf-8")
        identity_candidate_path.write_text(json.dumps(identity_candidate), encoding="utf-8")
        identity_comparison = json.loads(run("compare", identity_baseline_path, identity_candidate_path, "--format", "json"))
        identity_changes = [row for row in identity_comparison["functions"] if row["function"] == "same_readable_name"]
        assert len(identity_changes) == 2, identity_changes
        assert any(row["events"]["baseline"] is not None and row["events"]["candidate"] is None for row in identity_changes)
        assert any(row["events"]["baseline"] is None and row["events"]["candidate"] is not None for row in identity_changes)
        assert identity_comparison["baseline"]["identity"] == "compiler_stable_ids"
        assert identity_comparison["candidate"]["identity"] == "compiler_stable_ids"
        legacy_candidate = copy.deepcopy(identity_baseline)
        del legacy_candidate["functions"][0]["identity_id"]
        legacy_candidate_path = work / "identity-legacy-candidate.json"
        legacy_candidate_path.write_text(json.dumps(legacy_candidate), encoding="utf-8")
        coverage_comparison = json.loads(run("compare", identity_baseline_path, legacy_candidate_path, "--format", "json"))
        assert coverage_comparison["baseline"]["identity"] == "compiler_stable_ids"
        assert coverage_comparison["candidate"]["identity"] == "source_name_fallback"
        assert any("stable identity coverage" in warning for warning in coverage_comparison["warnings"])
        run(
            "compare", identity_baseline_path, legacy_candidate_path, "--format", "json",
            "--max-function-self-regression-percent", "10", ok=False, expected=INCONCLUSIVE_STATUS,
        )
        contract_baseline = copy.deepcopy(identity_baseline)
        contract_candidate = copy.deepcopy(identity_baseline)
        contract_baseline["run"]["capabilities"] = {"identity": {
            "status": "compiler_stable_ids", "reason": "fixture", "namespace": "elisa.compiler.trace", "version": IDENTITY_CONTRACT_LEGACY_VERSION, "scope": "capture"
        }}
        contract_candidate["run"]["capabilities"] = {"identity": {
            "status": "compiler_stable_ids", "reason": "fixture", "namespace": "other.trace", "version": IDENTITY_CONTRACT_LEGACY_VERSION, "scope": "capture"
        }}
        contract_baseline_path = work / "identity-contract-baseline.json"
        contract_candidate_path = work / "identity-contract-candidate.json"
        contract_baseline_path.write_text(json.dumps(contract_baseline), encoding="utf-8")
        contract_candidate_path.write_text(json.dumps(contract_candidate), encoding="utf-8")
        contract_comparison = json.loads(run("compare", contract_baseline_path, contract_candidate_path, "--format", "json"))
        assert contract_comparison["baseline"]["identity_namespace"] == "elisa.compiler.trace"
        assert contract_comparison["candidate"]["identity_namespace"] == "other.trace"
        assert any("stable identity coverage or contract" in warning for warning in contract_comparison["warnings"])
        run(
            "compare", contract_baseline_path, contract_candidate_path, "--format", "json",
            "--max-function-self-regression-percent", "10", ok=False, expected=INCONCLUSIVE_STATUS,
        )
        version_candidate = copy.deepcopy(contract_baseline)
        version_candidate["run"]["capabilities"]["identity"]["version"] = IDENTITY_CONTRACT_CURRENT_VERSION
        version_candidate_path = work / "identity-version-candidate.json"
        version_candidate_path.write_text(json.dumps(version_candidate), encoding="utf-8")
        version_comparison = json.loads(run("compare", contract_baseline_path, version_candidate_path, "--format", "json"))
        assert version_comparison["baseline"]["identity_namespace"] == "elisa.compiler.trace"
        assert version_comparison["candidate"]["identity_namespace"] == "elisa.compiler.trace"
        assert version_comparison["baseline"]["identity_version"] == IDENTITY_CONTRACT_LEGACY_VERSION
        assert version_comparison["candidate"]["identity_version"] == IDENTITY_CONTRACT_CURRENT_VERSION
        assert any("stable identity coverage or contract" in warning for warning in version_comparison["warnings"])
        run(
            "compare", contract_baseline_path, version_candidate_path, "--format", "json",
            "--max-function-self-regression-percent", "10", ok=False, expected=INCONCLUSIVE_STATUS,
        )
        assert comparison["metrics"]["execution_ms_mean"]["baseline"] == 1.25
        report["locations"] = [{
            "kind": "value", "function": "main", "line": 1, "count": 1,
            "interval_ns": 10, "max_interval_ns": 10, "compiler_line": 1,
            "source": report["source"], "source_text": None, "variable": "x",
            "signed": True, "minimum": -2, "maximum": 3, "sum": -1, "last": 2,
        }]
        capture.write_text(json.dumps(report), encoding="utf-8")
        comparison = json.loads(run("compare", capture, capture, "--format", "json"))
        assert comparison["status"] == "ok"
        report["locations"][0]["sum"] = None
        report["locations"][0]["sum_overflow"] = True
        capture.write_text(json.dumps(report), encoding="utf-8")
        comparison = json.loads(run("compare", capture, capture, "--format", "json"))
        assert comparison["status"] == "ok"
        report["locations"][0]["sum"] = -1
        capture.write_text(json.dumps(report), encoding="utf-8")
        run("compare", capture, capture, "--format", "json", ok=False)
        del report["locations"][0]["sum_overflow"]
        report["summary"]["dropped_call_edges"] = 1
        capture.write_text(json.dumps(report))
        comparison = json.loads(run("compare", capture, capture, "--format", "json"))
        assert comparison["status"] == "warning"
        report["summary"]["dropped_call_edges"] = 0
        report["summary"]["stack_overflow_entries"] = 1
        capture.write_text(json.dumps(report))
        report["source_snapshot"] = {
            "sha256": hashlib.sha256(b"embedded source").hexdigest(),
            "content": "embedded source",
        }
        report["workload"] = {
            "source_sha256": hashlib.sha256(report["source"].encode()).hexdigest(),
            "source_size_bytes": len(report["source"].encode()),
            "working_directory": "/tmp/elisa-fixture",
            "stdin": {"path": "input.dat", "sha256": None},
            "environment_override_keys": ["ELISA_FIXTURE"],
            "arguments": ["--fixture", "<unsafe>"],
            "reproducibility": {
                "random_seed": None,
                "random_seed_source": "not_controlled",
                "environment_values": "redacted",
                "inputs_hashed": True,
            },
        }
        report["source_snapshot"]["content"] = "embedded <source>"
        report["source_snapshot"]["sha256"] = hashlib.sha256(b"embedded <source>").hexdigest()
        capture.write_text(json.dumps(report), encoding="utf-8")
        assert run("report", capture, "--format", "text").startswith(b"Elisa profiler")
        embedded_html = run("report", capture, "--format", "html")
        assert b"Source view" in embedded_html
        assert b"source-filter" in embedded_html
        assert b"source-line" in embedded_html
        assert b"embedded &lt;source&gt;" in embedded_html
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
        assert b"<dt>Outcome</dt><dd>success</dd>" in offline_html
        assert b"<dt>Host</dt><dd>Darwin / arm64</dd>" in offline_html
        assert b"<dt>Affinity</dt><dd>inherited; unchanged</dd>" in offline_html
        assert b"<dt>Locations</dt><dd>2</dd>" in offline_html
        assert b"<dt>Mean execution</dt><dd>1.250 ms</dd>" in offline_html
        assert b"<dt>CPU</dt><dd>unavailable</dd>" in offline_html
        assert b"<dt>Measured repetitions</dt><dd>0</dd>" in offline_html
        assert b"edge-filter" in offline_html
        assert b"location-filter" in offline_html
        assert b"Flame graph" in offline_html
        assert b"flame-filter" in offline_html
        assert b"function formatShare(value)" in offline_html
        assert b"function-root-weights" in offline_html
        assert b"observed folded root self time" in offline_html
        assert b"Workload reproducibility" in offline_html
        assert b"ELISA_FIXTURE" in offline_html
        assert b"&lt;unsafe&gt;" in offline_html
        assert b"Diagnostics" in offline_html
        assert b"Stack depth overflow occurred 1 time(s)" in offline_html

        large_weights = copy.deepcopy(report)
        large_weights["run"]["location_timing"] = True
        large_weights["stacks"] = [
            {"stack": "root", "call_events": 1, "completed_calls": 1, "self_ns": I64_MAX},
            {"stack": "root;tail", "call_events": 1, "completed_calls": 1, "self_ns": 1},
        ]
        capture.write_text(json.dumps(large_weights), encoding="utf-8")
        large_speedscope = json.loads(run("report", capture, "--format", "speedscope"))
        assert large_speedscope["profiles"][0]["endValue"] == I64_MAX
        assert large_speedscope["profiles"][0]["weights"] == [I64_MAX, 1]
        capture.write_text(json.dumps(report), encoding="utf-8")

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
        live_html_path = work / "live.html"
        run("profile", ROOT / "examples/hot_loop.elisa", "--env", "ELISA_FIXTURE=supersecret", "--format", "html", "--output", live_html_path, "--", "--fixture")
        live_html = live_html_path.read_bytes()
        assert b"Workload reproducibility" in live_html
        assert b"--fixture" in live_html
        assert b"ELISA_FIXTURE" in live_html
        assert b"supersecret" not in live_html
        assert b"Diagnostics" in live_html
        assert b"No recorded capture-quality degradations" in live_html
        assert b"Source view" in live_html
        assert b"source-filter" in live_html
        assert b"source-line" in live_html
        assert b"function hasMatch(node,query)" in live_html
        assert b"function formatShare(value)" in live_html
        assert b"function-root-weights" in live_html
        assert b"Inclusive callers overlap their callees" in live_html
        assert b".split(/\\n+/)" not in live_html

        invalid_millis = json.dumps(report).replace(
            '"execution_ms_mean": 1.25', '"execution_ms_mean": 01.25')
        capture.write_text(invalid_millis, encoding="utf-8")
        run("compare", capture, capture, "--format", "json", ok=False)
        for malformed in ('9223372036854775808', '7garbage', '07', '7.1'):
            capture.write_text(json.dumps(report).replace('"events": 7', '"events": ' + malformed))
            run("compare", capture, capture, "--format", "json", ok=False)
        valid_report_json = json.dumps(report)
        capture.write_text(valid_report_json + "\n", encoding="utf-8")
        assert run("report", capture, "--format", "folded") == b"root 1\nroot;work 6\n"
        capture.write_text(valid_report_json + " trailing", encoding="utf-8")
        run("report", capture, "--format", "folded", ok=False)
        capture.write_text("[]", encoding="utf-8")
        run("report", capture, "--format", "folded", ok=False)
        invalid_escape_json = valid_report_json.replace('"run": {', r'"run": {"unknown":"\q",', 1)
        capture.write_text(invalid_escape_json, encoding="utf-8")
        run("report", capture, "--format", "folded", ok=False)
        mismatched_array_json = valid_report_json.replace('"stacks": [', '"stacks": [{"broken":]', 1)
        capture.write_text(mismatched_array_json, encoding="utf-8")
        run("report", capture, "--format", "folded", ok=False)
        mismatched_object_json = valid_report_json.replace('"run": {', '"run": [{', 1)
        capture.write_text(mismatched_object_json, encoding="utf-8")
        run("report", capture, "--format", "folded", ok=False)
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
        invalid_function_location = copy.deepcopy(report)
        invalid_function_location["locations"] = [{
            "kind": "function", "function": "broken", "line": 1, "count": 1,
            "interval_ns": 10, "max_interval_ns": 10, "compiler_line": 1,
            "source": invalid_function_location["source"], "source_text": None,
            "inclusive_ns": 10, "self_ns": 10, "completed_calls": 2,
        }]
        capture.write_text(json.dumps(invalid_function_location), encoding="utf-8")
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
        run("profile", ROOT / "examples/hot_loop.elisa", "--env", "ELISA_PROFILE_FD=1", ok=False)
        target = work / "target.elisa"
        target.write_text("def main() -> i64:\n    return 7\n")
        run("profile", target, "--format", "json", "--output", output, expected=7)
        failed_report = json.loads(output.read_text())
        assert failed_report["run"]["exit_code"] == 7
        assert failed_report["run"]["outcome"] == "target_exit"
        assert failed_report["workload"]["source_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
        dependency_target = work / "dependency-target.elisa"
        dependency_helper = work / "dependency-helper.elisa"
        dependency_helper.write_text("def helper() -> i64:\n    return 1\n", encoding="utf-8")
        dependency_target.write_text(
            'include "dependency-helper.elisa"\n\n'
            "def main() -> i64:\n"
            "    return 0 if helper() == 1 else 1\n",
            encoding="utf-8",
        )
        run("profile", dependency_target, "--format", "json", "--output", output)
        dependency_first = json.loads(output.read_text(encoding="utf-8"))
        dependency_source_digest = dependency_first["workload"]["source_sha256"]
        dependency_tree_digest = dependency_first["workload"]["source_tree_sha256"]
        assert len(dependency_tree_digest) == 64
        dependency_helper.write_text("def helper() -> i64:\n    return 2\n", encoding="utf-8")
        run("profile", dependency_target, "--format", "json", "--output", output, expected=1)
        dependency_second = json.loads(output.read_text(encoding="utf-8"))
        assert dependency_second["workload"]["source_sha256"] == dependency_source_digest
        assert dependency_second["workload"]["source_tree_sha256"] != dependency_tree_digest
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
        assert crash_report["run"]["outcome"] == "target_signal"
        assert crash_report["run"]["signal"] == 6
        assert crash_report["summary"]["crash_signal"] == 6
        assert crash_report["quality"]["capture"] == "target_signal"
        assert crash_report["quality"]["detail"] == "degraded"
        assert "crash_marker" in crash_report["quality"]["reasons"]
        assert crash_report["active_stack"]["tracked_depth"] >= 1
        assert crash_report["active_stack"]["overflow_depth"] == 0
        assert crash_report["active_stack"]["stack"][-1] == "main"

        interrupted_output = work / "interrupted-stack.json"
        run("profile", ROOT / "examples/interrupted_stack.elisa", "--format", "json", "--output", interrupted_output, expected=134)
        interrupted = json.loads(interrupted_output.read_text(encoding="utf-8"))
        assert interrupted["run"]["outcome"] == "target_signal"
        assert interrupted["run"]["signal"] == 6
        assert interrupted["summary"]["capture_complete"] is False
        assert interrupted["quality"]["capture"] == "target_signal"
        assert interrupted["quality"]["detail"] == "degraded"
        assert "crash_marker" in interrupted["quality"]["reasons"]
        assert interrupted["active_stack"]["tracked_depth"] >= 1
        assert interrupted["active_stack"]["overflow_depth"] == 0
        assert interrupted["active_stack"]["stack"][0] == "main"
        assert all(frame == "descend" for frame in interrupted["active_stack"]["stack"][1:])
        interrupted_text_output = work / "interrupted-stack.txt"
        run("profile", ROOT / "examples/interrupted_stack.elisa", "--format", "text", "--output", interrupted_text_output, expected=134)
        interrupted_text = interrupted_text_output.read_bytes()
        assert b"active stack (tracked depth" in interrupted_text
        assert b"main;descend" in interrupted_text
        assert b"capability boundary: sampling unsupported" in interrupted_text
        interrupted_html_output = work / "interrupted-stack.html"
        run("profile", ROOT / "examples/interrupted_stack.elisa", "--format", "html", "--output", interrupted_html_output, expected=134)
        interrupted_html = interrupted_html_output.read_bytes()
        assert b"Interrupted active stack" in interrupted_html
        assert b"diagnostic evidence, not completed-call evidence" in interrupted_html
        assert b"Capability boundary" in interrupted_html
        assert b"Allocation:</strong> unsupported" in interrupted_html

        run("profile", ROOT / "examples/hot_loop.elisa", "--repeat", "2",
            "--event-trace", "--max-event-trace-events", "10",
            "--format", "json", "--output", output)
        measured = json.loads(output.read_text())
        assert measured["schema_version"] == 2
        assert measured["envelope"] == {
            "major": 2,
            "minor": 0,
            "kind": "profile",
            "compatibility": "backward-compatible-v1",
        }
        assert measured["run"]["outcome"] == "success"
        assert measured["functions"]
        assert all(record["inclusive_percent"] is None and record["self_percent"] is None for record in measured["functions"])
        host = measured["host"]
        assert host["os"] in {"Darwin", "Linux"}, host
        assert host["architecture"], host
        assert host["affinity"] == {"policy": "inherited", "changed": False}, host
        assert host["power_thermal"] is None, host
        assert host["load_average_source"] == "getloadavg", host
        assert isinstance(host["load_average_1m"], float), host
        assert measured["run"]["collection_mode"] == "full"
        assert measured["run"]["capabilities"]["event_classes"] == ["function", "statement", "value"]
        assert measured["run"]["capabilities"]["sampling"] == "unsupported"
        assert measured["run"]["capabilities"]["sampling_detail"] == {
            "status": "unsupported", "reason": "no_native_sampler_backend", "scope": "none"
        }
        assert measured["run"]["capabilities"]["allocation"] == {
            "status": "unsupported", "reason": "allocator_lifecycle_hooks_unavailable", "scope": "none"
        }
        assert measured["run"]["capabilities"]["tasks"] == {
            "status": "unsupported", "reason": "task_lifecycle_hooks_unavailable", "scope": "none"
        }
        assert measured["run"]["capabilities"]["identity"] == {
            "status": "compiler_stable_ids", "reason": "compiler_issued_function_and_location_ids",
            "namespace": "elisa.compiler.trace", "version": IDENTITY_CONTRACT_CURRENT_VERSION, "scope": "capture"
        }
        assert measured["capture"] == {
            "process": {"scope": "single_profiled_child", "lifetime": "launch_to_wait"},
            "threads": {
                "scope": "registered_collector_threads",
                "lifetime": "capture_only",
                "identity": "local_capture_thread_id",
            },
            "tasks": {"status": "not_recorded"},
            "repetition": {"scope": "run.repetitions", "warmups_excluded": True},
            "clock": {"domain": "wall", "unit": "ns", "source": "CLOCK_MONOTONIC"},
        }
        assert measured["numeric_encoding"] == {
            "integer": "decimal_json_integer",
            "large_integer_policy": "preserve_decimal_text",
            "viewer_metric_parser": "raw_json_to_BigInt",
            "javascript_safe_integer": "2^53_minus_1",
        }
        assert measured["run"]["capabilities"]["timing"] == "wall"
        assert measured["summary"]["capture_started"] is True
        assert measured["summary"]["capture_complete"] is True
        manifest = json.loads(Path(str(output) + ".manifest.json").read_text(encoding="utf-8"))
        assert manifest["capture_index"]["format"] == "record-framed-v1"
        assert manifest["capture_index"]["bytes"] >= manifest["capture_index"]["valid_bytes"] > 0
        assert manifest["capture_index"]["valid_frames"] > 0
        assert len(measured["workload"]["source_sha256"]) == 64
        assert all(character in "0123456789abcdef" for character in measured["workload"]["source_sha256"])
        assert measured["workload"]["reproducibility"] == {
            "random_seed": None,
            "random_seed_source": "not_controlled",
            "environment_values": "redacted",
            "inputs_hashed": True,
        }
        repetitions = measured["run"]["repetitions"]
        assert len(repetitions) == 2
        assert all(
            set(item["detail_records"])
            == {"locations", "functions", "call_edges", "stacks", "thread_loss"}
            for item in repetitions
        )
        assert measured["thread_loss"]

        generic_identity_output = work / "generic-identity.json"
        run("profile", ROOT / "examples/generic_identity.elisa",
            "--format", "json", "--output", generic_identity_output)
        generic_identity = json.loads(generic_identity_output.read_text())
        generic_records = [
            record for record in generic_identity["functions"]
            if record["function"] == "identity"
        ]
        assert len(generic_records) == 2, generic_identity["functions"]
        assert len({record["identity_id"] for record in generic_records}) == 2
        assert all(record["completed_calls"] == 1 for record in generic_records)

        module_identity_output = work / "module-identity.json"
        run("profile", ROOT / "examples/module_identity.elisa",
            "--format", "json", "--output", module_identity_output)
        module_identity = json.loads(module_identity_output.read_text())
        module_records = [
            record for record in module_identity["functions"]
            if record["function"] == "same"
        ]
        assert len(module_records) == 2, module_identity["functions"]
        assert len({record["identity_id"] for record in module_records}) == 2
        assert all(record["completed_calls"] == 1 for record in module_records)
        assert all(
            set(record)
            == {
                "repetition",
                "thread_id",
                "events",
                "location_dropped",
                "call_edge_dropped",
                "stack_dropped",
                "trace_dropped",
                "bytes_dropped",
                "event_start",
                "event_end",
            }
            for record in measured["thread_loss"]
        )
        assert all(record["events"] > 0 for record in measured["thread_loss"])
        assert all(record["event_start"] is not None for record in measured["thread_loss"])
        assert all(record["event_end"] is not None for record in measured["thread_loss"])
        assert all(record["event_start"] <= record["event_end"] for record in measured["thread_loss"])
        assert {record["repetition"] for record in measured["thread_loss"]} == {1, 2}
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
        assert all(set(item["completeness"]) == {
            "events", "locations", "functions", "call_edges", "stacks", "timings", "resources"
        } for item in repetitions)
        assert all(item["completeness"]["resources"] == "exact" for item in repetitions)
        assert all(item["completeness"]["timings"] == "exact" for item in repetitions)
        mean_of_middle = sum(item["execution_ms"] for item in repetitions) / 2
        assert abs(measured["run"]["execution_ms_median"] - mean_of_middle) <= 0.002
        expected_stdev = statistics.stdev(item["execution_ms"] for item in repetitions)
        assert abs(measured["run"]["execution_ms_stdev"] - expected_stdev) <= 0.002
        assert measured["run"]["execution_ci95_available"] is True
        assert measured["run"]["execution_ms_ci95_low"] <= measured["run"]["execution_ms_mean"]
        assert measured["run"]["execution_ms_ci95_high"] >= measured["run"]["execution_ms_mean"]
        assert measured["run"]["execution_ms_ci95_high"] > measured["run"]["execution_ms_ci95_low"]

        recursive_output = work / "recursive.json"
        run("profile", ROOT / "examples/recursive.elisa", "--format", "json", "--output", recursive_output)
        recursive = json.loads(recursive_output.read_text(encoding="utf-8"))
        recursive_functions = {item["function"]: item for item in recursive["functions"]}
        assert recursive_functions["countdown"]["call_events"] == RECURSIVE_CALLS
        assert recursive_functions["countdown"]["completed_calls"] == RECURSIVE_CALLS
        assert recursive_functions["countdown"]["self_ns"] <= recursive_functions["countdown"]["inclusive_ns"]
        recursive_edges = {(item["caller"], item["callee"]): item for item in recursive["call_edges"]}
        assert recursive_edges[("main", "countdown")]["completed_calls"] == 1
        assert recursive_edges[("countdown", "countdown")]["call_events"] == RECURSIVE_CALLS - 1
        assert recursive_edges[("countdown", "countdown")]["completed_calls"] == RECURSIVE_CALLS - 1
        assert recursive["stacks"]
        assert all(item["completed_calls"] <= item["call_events"] for item in recursive["stacks"])

        threaded_output = work / "threaded.json"
        run("profile", ROOT / "examples/threaded.elisa", "--format", "json", "--output", threaded_output)
        threaded = json.loads(threaded_output.read_text(encoding="utf-8"))
        assert threaded["summary"]["thread_count"] >= 3
        assert len(threaded["thread_loss"]) >= 3
        assert all(record["repetition"] == 1 for record in threaded["thread_loss"])
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
