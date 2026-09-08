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

from profile_schema_smoke import SchemaError, validate

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
TARGET_EXIT_CODE = 126
COLLECTOR_STATUS_OK = 1


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
    help_text = run("--help")
    assert b"Usage: elisa-profiler COMMAND" in help_text
    assert b"-- TARGET_ARGS..." in help_text
    assert run("-h") == help_text
    assert run("help") == help_text
    for command in ("profile", "record", "report", "recover", "compare", "benchmark", "baseline", "doctor"):
        assert run(command, "--help") == help_text
        assert run(command, "-h") == help_text
        assert run("help", command) == help_text
    run("help", "unknown", ok=False)
    run("--help", "extra", ok=False)
    run("help", "profile", "extra", ok=False)
    isolated_help = subprocess.run(
        [str(NATIVE), "--help"], capture_output=True, timeout=TIMEOUT_SECONDS,
        env={**os.environ, "ELISA_COMPILER_ROOT": "/nonexistent/elisa-help-test"})
    assert isolated_help.returncode == 0 and isolated_help.stdout == help_text
    assert isolated_help.stderr == b""
    # Keep the lightweight schema verifier honest at both integer boundaries.
    allocation_schema_root = json.loads((ROOT / "docs/profile.schema.json").read_text(encoding="utf-8"))
    address_schema = allocation_schema_root["$defs"]["allocation_event"]["properties"]["address"]
    validate(0, address_schema, allocation_schema_root, "address")
    validate(IDENTITY_ID_CANDIDATE, address_schema, allocation_schema_root, "address")
    for invalid_address in (-1, IDENTITY_ID_CANDIDATE + 1):
        try:
            validate(invalid_address, address_schema, allocation_schema_root, "address")
        except SchemaError:
            pass
        else:
            raise AssertionError("schema accepted an out-of-range address")
    exclusive_schema = {"type": "integer", "exclusiveMaximum": IDENTITY_ID_CANDIDATE}
    validate(IDENTITY_ID_CANDIDATE - 1, exclusive_schema, exclusive_schema, "boundary")
    try:
        validate(IDENTITY_ID_CANDIDATE, exclusive_schema, exclusive_schema, "boundary")
    except SchemaError:
        pass
    else:
        raise AssertionError("schema accepted its exclusive maximum")
    for value, constraint in (
        ("", {"minLength": 1}), ("ab", {"maxLength": 1}),
        ("not-a-digest", {"pattern": "^[0-9a-f]{64}$"}),
        ([0, 1], {"maxItems": 1}),
    ):
        try:
            validate(value, constraint, constraint, "constraint")
        except SchemaError:
            pass
        else:
            raise AssertionError(f"schema ignored constraint {constraint}")
    validate("λ", {"minLength": 1, "maxLength": 1}, {}, "unicode")
    validate(None, {"type": ["string", "null"], "pattern": "^[0-9]+$"}, {}, "nullable")
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
            "compile_ms": 2.5, "collection_mode": "diagnostic", "location_timing": True,
            "repetitions": [{
                "repetition": 1,
                "event_trace": [
                    {"sequence": 0, "kind": "function", "function": "root", "line": 1, "repetition": 1,
                     "variable": None, "signed": False, "value": 0, "thread_id": 0,
                     "timestamp_ns": 100},
                    {"sequence": 1, "kind": "statement", "function": "work", "line": 2, "repetition": 1,
                     "variable": "value", "signed": False, "value": 7, "thread_id": 0,
                     "timestamp_ns": 200},
                ],
            }, {
                "repetition": 2,
                "event_trace": [{
                    "sequence": 0, "kind": "function", "function": "root", "line": 1, "repetition": 2,
                    "variable": None, "signed": False, "value": 0, "thread_id": 0,
                    "timestamp_ns": 300,
                }],
            }],
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
        forwarded_help = json.loads(run("profile", ROOT / "examples" / "hot_loop.elisa", "--", "--help"))
        assert forwarded_help["workload"]["arguments"] == ["--help"]
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
        assert len(identity_changes) == 1, identity_changes
        assert identity_changes[0]["match"] == "structural", identity_changes
        assert identity_changes[0]["events"]["baseline"] is not None
        assert identity_changes[0]["events"]["candidate"] is not None
        assert identity_comparison["baseline"]["identity"] == "compiler_stable_ids"
        assert identity_comparison["candidate"]["identity"] == "compiler_stable_ids"
        structural_detail_baseline = copy.deepcopy(report)
        structural_detail_candidate = copy.deepcopy(report)
        structural_detail_baseline["functions"] = [identity_function]
        structural_detail_candidate["functions"] = [dict(identity_function, identity_id=IDENTITY_ID_CANDIDATE)]
        edge = {
            "caller": "caller", "callee": "callee", "caller_id": 100, "callee_id": 101,
            "call_events": 2, "completed_calls": 2, "inclusive_ns": 20,
        }
        structural_detail_baseline["call_edges"] = [edge]
        structural_detail_candidate["call_edges"] = [dict(edge, caller_id=200, callee_id=201)]
        for index, stack in enumerate(structural_detail_baseline["stacks"]):
            stack["stack_ids"] = str(index + 1)
        for index, stack in enumerate(structural_detail_candidate["stacks"]):
            stack["stack_ids"] = str(index + 10)
        structural_detail_baseline_path = work / "detail-structural-baseline.json"
        structural_detail_candidate_path = work / "detail-structural-candidate.json"
        structural_detail_baseline_path.write_text(json.dumps(structural_detail_baseline), encoding="utf-8")
        structural_detail_candidate_path.write_text(json.dumps(structural_detail_candidate), encoding="utf-8")
        structural_detail_comparison = json.loads(run("compare", structural_detail_baseline_path, structural_detail_candidate_path, "--format", "json"))
        assert {row["match"] for row in structural_detail_comparison["functions"]} == {"structural"}
        assert {row["match"] for row in structural_detail_comparison["call_edges"]} == {"structural"}
        assert {row["match"] for row in structural_detail_comparison["stacks"]} == {"structural"}
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
        run(
            "compare", identity_baseline_path, identity_baseline_path, "--format", "json",
            "--max-function-self-regression-percent", "10", ok=False, expected=INCONCLUSIVE_STATUS,
        )
        legacy_identity = copy.deepcopy(report)
        legacy_identity["functions"] = [
            {key: value for key, value in identity_function.items() if key != "identity_id"}
        ]
        ambiguous_candidate = copy.deepcopy(legacy_identity)
        ambiguous_candidate["functions"].append(copy.deepcopy(ambiguous_candidate["functions"][0]))
        legacy_identity_path = work / "identity-legacy.json"
        ambiguous_candidate_path = work / "identity-ambiguous-candidate.json"
        legacy_identity_path.write_text(json.dumps(legacy_identity), encoding="utf-8")
        ambiguous_candidate_path.write_text(json.dumps(ambiguous_candidate), encoding="utf-8")
        ambiguity_comparison = json.loads(run("compare", legacy_identity_path, ambiguous_candidate_path, "--format", "json"))
        assert any("ambiguous additions/removals" in warning for warning in ambiguity_comparison["warnings"])
        assert {row["match"] for row in ambiguity_comparison["functions"]} == {"ambiguous"}, ambiguity_comparison["functions"]
        run(
            "compare", legacy_identity_path, ambiguous_candidate_path, "--format", "json",
            "--max-function-self-regression-percent", "10", ok=False, expected=INCONCLUSIVE_STATUS,
        )
        legacy_same_comparison = json.loads(run("compare", legacy_identity_path, legacy_identity_path, "--format", "json"))
        assert {row["match"] for row in legacy_same_comparison["functions"]} == {"readable_name"}, legacy_same_comparison["functions"]
        mixed_identity = copy.deepcopy(identity_baseline)
        mixed_identity["functions"].append({key: value for key, value in identity_function.items() if key != "identity_id"})
        mixed_identity_path = work / "identity-mixed.json"
        mixed_identity_path.write_text(json.dumps(mixed_identity), encoding="utf-8")
        run("compare", mixed_identity_path, mixed_identity_path, "--format", "json", ok=False)
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
        structural_baseline = copy.deepcopy(report)
        structural_candidate = copy.deepcopy(report)
        structural_baseline["locations"][0]["identity_id"] = IDENTITY_ID_BASELINE
        structural_candidate["locations"][0]["identity_id"] = IDENTITY_ID_CANDIDATE
        structural_baseline_path = work / "location-structural-baseline.json"
        structural_candidate_path = work / "location-structural-candidate.json"
        structural_baseline_path.write_text(json.dumps(structural_baseline), encoding="utf-8")
        structural_candidate_path.write_text(json.dumps(structural_candidate), encoding="utf-8")
        structural_comparison = json.loads(run("compare", structural_baseline_path, structural_candidate_path, "--format", "json"))
        structural_rows = [row for row in structural_comparison["locations"] if row["function"] == "main"]
        assert len(structural_rows) == 1, structural_rows
        assert structural_rows[0]["match"] == "structural", structural_rows
        ambiguous_structural_candidate = copy.deepcopy(structural_candidate)
        ambiguous_structural_candidate["locations"].append(dict(ambiguous_structural_candidate["locations"][0], identity_id=IDENTITY_ID_CANDIDATE - 1))
        ambiguous_structural_candidate_path = work / "location-structural-ambiguous-candidate.json"
        ambiguous_structural_candidate_path.write_text(json.dumps(ambiguous_structural_candidate), encoding="utf-8")
        ambiguous_structural_comparison = json.loads(run("compare", structural_baseline_path, ambiguous_structural_candidate_path, "--format", "json"))
        ambiguous_structural_rows = [row for row in ambiguous_structural_comparison["locations"] if row["function"] == "main"]
        assert len(ambiguous_structural_rows) == 1, ambiguous_structural_rows
        assert ambiguous_structural_rows[0]["match"] == "ambiguous", ambiguous_structural_rows
        assert any("ambiguous additions/removals" in warning for warning in ambiguous_structural_comparison["warnings"])
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
        offline_text = run("report", capture, "--format", "text")
        assert offline_text.startswith(b"Elisa profiler")
        assert b"collection mode: diagnostic" in offline_text
        embedded_html = run("report", capture, "--format", "html")
        assert b"Source view" in embedded_html
        assert b"source-filter" in embedded_html
        assert b"source-line" in embedded_html
        assert b"color is paired with border patterns" in embedded_html
        assert b"embedded &lt;source&gt;" in embedded_html
        hostile_report = copy.deepcopy(report)
        hostile_source = "<script>alert('source')</script>&\""
        hostile_source_content = "<img src=x onerror=\"alert('source')\"> & '"
        hostile_report["source"] = hostile_source
        hostile_report["workload"]["working_directory"] = "<script>alert('directory')</script>&\"'"
        hostile_report["workload"]["arguments"] = [hostile_source_content]
        hostile_report["source_snapshot"]["content"] = hostile_source_content
        hostile_report["source_snapshot"]["sha256"] = hashlib.sha256(hostile_source_content.encode()).hexdigest()
        capture.write_text(json.dumps(hostile_report), encoding="utf-8")
        hostile_html = run("report", capture, "--format", "html")
        assert b"&lt;script&gt;alert(&#39;source&#39;)&lt;/script&gt;&amp;&quot;" in hostile_html
        assert b"&lt;img src=x onerror=&quot;alert(&#39;source&#39;)&quot;&gt; &amp; &#39;" in hostile_html
        assert b"<script>alert('source')</script>" not in hostile_html
        assert b"<img src=x onerror=\"alert('source')\">" not in hostile_html
        assert b"<script>alert('directory')</script>" not in hostile_html
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
        assert b"<dt>Collection mode</dt><dd>diagnostic</dd>" in offline_html
        assert b"<dt>Measured repetitions</dt><dd>0</dd>" in offline_html
        assert b"edge-filter" in offline_html
        assert b"location-filter" in offline_html
        assert b"Flame graph" in offline_html
        assert "Flame graph — metric: events".encode() in offline_html
        assert b"flame-filter" in offline_html
        assert b"flame-direction" in offline_html
        assert b"flame-metric-title" in offline_html
        assert b"flame-metric" in offline_html
        assert b"flame-metric-filter" in offline_html
        assert b"DEFAULT_VALUES" in offline_html
        assert b"CHANGE_EVENT='change'" in offline_html
        assert b"completed_calls" in offline_html
        assert b"call_events" in offline_html
        assert b"Direction: caller" in offline_html
        assert b"recursive" in offline_html
        assert b"function formatShare(value)" in offline_html
        assert b"function-root-weights" in offline_html
        assert b"observed folded root self time" in offline_html
        assert b"Loading function records" in offline_html
        assert b"No function records were captured" in offline_html
        assert b"Enable JavaScript to inspect hotspots interactively" in offline_html
        assert b"@media(prefers-reduced-motion:reduce)" in offline_html
        assert b"@media print" in offline_html
        assert b"search:(field(record,'function')+' '+formatShare" in offline_html
        assert b"Where to start" in offline_html
        assert b"actionable-title" in offline_html
        assert b"MAX_ACTIONABLE_ROWS=5" in offline_html
        assert b"Workload reproducibility" in offline_html
        assert b"ELISA_FIXTURE" in offline_html
        assert b"&lt;unsafe&gt;" in offline_html
        assert b"Diagnostics" in offline_html
        assert b"Thread-loss intervals" in offline_html
        assert b"thread-loss-filter" in offline_html
        assert b"INPUT_IDS=['function-filter'" in offline_html
        assert b"thread-loss-filter']" in offline_html
        assert b"Sequence ranges are collector order only" in offline_html
        assert b"Diagnostic event evidence" in offline_html
        assert b"event-timeline-filter" in offline_html
        assert b"event-timeline-repetition" in offline_html
        assert b"event-timeline-thread" in offline_html
        assert b"event-timeline-selection" in offline_html
        assert b"event-timeline-kind" in offline_html
        assert b"event-timeline-start" in offline_html
        assert b"event-timeline-end" in offline_html
        assert b"MAX_EVENT_TIMELINE_ROWS=200" in offline_html
        assert b"MAX_EVENT_TIMELINE_INDEX=10000" in offline_html
        assert b"MAX_EVENT_TIMELINE_FILTER_OPTIONS=128" in offline_html
        assert b"timestamp_ns" in offline_html
        assert b"<th scope='col'>Repetition</th>" in offline_html
        assert offline_html.count(b'&quot;repetition&quot;: 2') >= 1
        assert b"Stack depth overflow occurred 1 time(s)" in offline_html
        assert b"Source view unavailable" in offline_html
        assert b"--embed-source" in offline_html
        source_override = work / "verified-source.elisa"
        source_override.write_bytes(report["source"].encode("utf-8"))
        overridden_html = run("report", capture, "--format", "html", "--source", source_override)
        assert b"Source view" in overridden_html
        assert b"source-filter" in overridden_html
        assert b"snapshot SHA-256" in overridden_html
        assert b"color is paired with border patterns" in overridden_html
        assert b"Source view unavailable" not in overridden_html

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
        assert b"Thread-loss intervals" in live_html
        assert b"thread-loss-filter" in live_html
        assert b"Sequence ranges are collector order only" in live_html
        assert b"No recorded capture-quality degradations" in live_html
        assert b"Source view" in live_html
        assert b"source-filter" in live_html
        assert b"source-metric" in live_html
        assert b"Observation count" in live_html
        assert b"METRIC_INTERVAL='interval_ns'" in live_html
        assert b"source-line" in live_html
        assert b"function hasMatch(node,query)" in live_html
        assert b"function formatShare(value)" in live_html
        assert b"function-root-weights" in live_html
        assert b"Inclusive callers overlap their callees" in live_html
        assert b"Observed callers" in live_html
        assert b"Observed callees" in live_html
        assert b"MAX_RELATED_ROWS=20" in live_html
        assert b"function-selection-identity" in live_html
        assert b"dataset.identity" in live_html
        assert b"calleeId===selectedIdentity" in live_html
        assert b"new MutationObserver(render)" in live_html
        assert b"Loading function records" in live_html
        assert b"No function records match this filter" in live_html
        assert b"Enable JavaScript to inspect hotspots interactively" in live_html
        assert b"@media(prefers-reduced-motion:reduce)" in live_html
        assert b"color is paired with border patterns" in live_html
        assert b"rows.addEventListener('click'" in live_html
        assert b"row.addEventListener('click'" not in live_html
        assert b"row.addEventListener('keydown'" not in live_html
        assert b".split(/\\n+/)" not in live_html

        invalid_millis = json.dumps(report).replace(
            '"execution_ms_mean": 1.25', '"execution_ms_mean": 01.25')
        capture.write_text(invalid_millis, encoding="utf-8")
        comparison_error = json.loads(run("compare", capture, capture, "--format", "json", ok=False))
        assert comparison_error["envelope"]["kind"] == "error", comparison_error
        assert comparison_error["error"]["code"] == "malformed_profile", comparison_error
        for malformed in ('9223372036854775808', '7garbage', '07', '7.1'):
            capture.write_text(json.dumps(report).replace('"events": 7', '"events": ' + malformed))
            run("compare", capture, capture, "--format", "json", ok=False)
        valid_report_json = json.dumps(report)
        capture.write_text(valid_report_json + "\n", encoding="utf-8")
        assert run("report", capture, "--format", "folded") == b"root 1\nroot;work 6\n"
        capture.write_text(valid_report_json + " trailing", encoding="utf-8")
        run("report", capture, "--format", "folded", ok=False)
        capture.write_text("[]", encoding="utf-8")
        malformed_profile_error = json.loads(run("report", capture, "--format", "json", ok=False))
        assert malformed_profile_error["envelope"]["kind"] == "error", malformed_profile_error
        assert malformed_profile_error["error"]["code"] == "malformed_profile_artifact", malformed_profile_error
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
        assert crash_report["run"]["outcome"] == "target_crash"
        assert crash_report["run"]["signal"] == 6
        assert crash_report["summary"]["crash_signal"] == 6
        assert crash_report["quality"]["capture"] == "target_crash"
        assert crash_report["quality"]["detail"] == "degraded"
        assert "crash_marker" in crash_report["quality"]["reasons"]
        assert crash_report["active_stack"]["tracked_depth"] >= 1
        assert crash_report["active_stack"]["overflow_depth"] == 0
        assert crash_report["active_stack"]["stack"][-1] == "main"

        interrupted_output = work / "interrupted-stack.json"
        run("profile", ROOT / "examples/interrupted_stack.elisa", "--format", "json", "--output", interrupted_output, expected=134)
        interrupted = json.loads(interrupted_output.read_text(encoding="utf-8"))
        assert interrupted["run"]["outcome"] == "target_crash"
        assert interrupted["run"]["signal"] == 6
        assert interrupted["summary"]["capture_complete"] is False
        assert interrupted["quality"]["capture"] == "target_crash"
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
        assert b"capability boundary: sampling disabled" in interrupted_text
        interrupted_html_output = work / "interrupted-stack.html"
        run("profile", ROOT / "examples/interrupted_stack.elisa", "--format", "html", "--output", interrupted_html_output, expected=134)
        interrupted_html = interrupted_html_output.read_bytes()
        assert b"Interrupted active stack" in interrupted_html
        assert b"diagnostic evidence, not completed-call evidence" in interrupted_html
        assert b"Capability boundary" in interrupted_html
        assert b"Allocation:</strong> active" in interrupted_html

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
        assert measured["run"]["capabilities"]["sampling"] == "disabled"
        assert measured["run"]["capabilities"]["sampling_detail"] == {
            "status": "disabled", "reason": "mode_not_selected", "scope": "none"
        }
        assert measured["run"]["capabilities"]["allocation"] == {
            "status": "active", "reason": "elisa_arena_hooks", "scope": "capture"
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
                "identity": "local_capture_thread_generation",
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
        allocation_output = work / "allocation.json"
        run("profile", ROOT / "examples" / "allocation_workload.elisa", "--mode", "diagnostic",
            "--format", "json", "--output", allocation_output)
        allocation_report = json.loads(allocation_output.read_text(encoding="utf-8"))
        allocation_events = allocation_report["run"]["repetitions"][0]["allocation_events"]
        assert allocation_events
        assert allocation_report["summary"]["allocation_events"] == len(allocation_events)
        assert allocation_report["run"]["capabilities"]["allocation"] == {
            "status": "active", "reason": "elisa_arena_hooks", "scope": "capture"
        }
        assert allocation_events[0]["kind"] == "region_create"
        assert allocation_events[0]["size_bytes"] > 0
        assert any(event["kind"] == "realloc_in_place" for event in allocation_events)
        assert b"Raw allocation lifecycle records" in run("report", allocation_output, "--format", "html")
        malformed_allocation = copy.deepcopy(allocation_report)
        malformed_allocation["run"]["repetitions"][0]["allocation_events"] = {}
        malformed_allocation_output = work / "malformed-allocation.json"
        malformed_allocation_output.write_text(json.dumps(malformed_allocation), encoding="utf-8")
        run("report", malformed_allocation_output, "--format", "html", ok=False)
        malformed_allocation_output.write_text(
            json.dumps(allocation_report).replace(
                json.dumps(allocation_events), json.dumps(allocation_events)[:-1] + ',]'), encoding="utf-8")
        run("report", malformed_allocation_output, "--format", "html", ok=False)
        allocation_html = work / "allocation.html"
        # Allocation evidence is a closed schema: every field must be present,
        # unsigned values retain uint64 precision, and identities agree with
        # the containing repetition and event kind.
        for field in allocation_events[0]:
            malformed_allocation = copy.deepcopy(allocation_report)
            del malformed_allocation["run"]["repetitions"][0]["allocation_events"][0][field]
            malformed_allocation_output.write_text(json.dumps(malformed_allocation), encoding="utf-8")
            run("report", malformed_allocation_output, "--format", "html", ok=False)
        for field, value in (
            ("address", -1), ("address", 2**64), ("size_bytes", "1"),
            ("timestamp_ns", None), ("thread_id", True), ("region", 1.5),
            ("kind", "alloc"), ("kind_code", 0), ("repetition", 2),
            ("unexpected", 0),
        ):
            malformed_allocation = copy.deepcopy(allocation_report)
            malformed_allocation["run"]["repetitions"][0]["allocation_events"][0][field] = value
            malformed_allocation_output.write_text(json.dumps(malformed_allocation), encoding="utf-8")
            run("report", malformed_allocation_output, "--format", "html", ok=False)
        wide_allocation = copy.deepcopy(allocation_report)
        wide_allocation["run"]["repetitions"][0]["allocation_events"][0]["address"] = 2**64 - 1
        malformed_allocation_output.write_text(json.dumps(wide_allocation), encoding="utf-8")
        assert str(2**64 - 1).encode() in run("report", malformed_allocation_output, "--format", "html")
        first_allocation_json = json.dumps(allocation_events[0])
        for malformed_record in (
            first_allocation_json[:-1] + ",}",
            first_allocation_json.replace(', "kind_code":', ' "kind_code":'),
            first_allocation_json.replace('"size_bytes":', '"address":'),
            first_allocation_json.replace('"old_address": 0', '"old_address": 00'),
        ):
            assert malformed_record != first_allocation_json
            malformed_allocation_output.write_text(
                json.dumps(allocation_report).replace(first_allocation_json, malformed_record, 1),
                encoding="utf-8")
            run("report", malformed_allocation_output, "--format", "html", ok=False)
        run("profile", ROOT / "examples" / "allocation_workload.elisa", "--mode", "diagnostic",
            "--format", "html", "--output", allocation_html)
        assert b"Memory and regions" in allocation_html.read_bytes()
        assert b"Raw allocation lifecycle records" in allocation_html.read_bytes()
        adoption_output = work / "arena-adoption.json"
        run("profile", ROOT / "examples" / "arena_adoption_workload.elisa", "--mode", "full",
            "--format", "json", "--output", adoption_output)
        adoption_report = json.loads(adoption_output.read_text(encoding="utf-8"))
        adoption_events = adoption_report["run"]["repetitions"][0]["allocation_events"]
        transfers = [event for event in adoption_events if event["kind"] == "arena_adopt"]
        assert len(transfers) == 1
        transfer = transfers[0]
        parent_arena, child_arena = transfer["arena"], transfer["old_address"]
        assert parent_arena != 0 and child_arena != 0 and parent_arena != child_arena
        for arena in (parent_arena, child_arena):
            assert any(event["kind"] == "alloc" and event["arena"] == arena
                       and event["sequence"] < transfer["sequence"] for event in adoption_events)
            assert any(event["kind"] == "region_free" and event["arena"] == arena
                       and event["sequence"] > transfer["sequence"] for event in adoption_events)
        assert b"arena_adopt" in run("report", adoption_output, "--format", "html")
        runtime_trace_output = work / "runtime-trace.json"
        run("profile", ROOT / "examples" / "runtime_trace_workload.elisa", "--mode", "full",
            "--format", "json", "--output", runtime_trace_output)
        runtime_trace_report = json.loads(runtime_trace_output.read_text(encoding="utf-8"))
        assert runtime_trace_report["summary"]["capture_complete"] is True
        assert runtime_trace_report["summary"]["function_events"] > 0
        assert any(function["function"] == "compute" for function in runtime_trace_report["functions"])
        assert measured["summary"]["capture_started"] is True
        assert measured["summary"]["capture_complete"] is True
        assert measured["source_mapping"]["mapped_locations"] == len(measured["locations"])
        assert measured["source_mapping"]["unmapped_locations"] == 0
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
        seeded_output = work / "seeded.json"
        run("profile", ROOT / "examples/hot_loop.elisa", "--random-seed", "42",
            "--format", "json", "--output", seeded_output)
        seeded = json.loads(seeded_output.read_text(encoding="utf-8"))
        assert seeded["workload"]["reproducibility"] == {
            "random_seed": "42",
            "random_seed_source": "cli",
            "environment_values": "redacted",
            "inputs_hashed": True,
        }
        environment_seed_output = work / "environment-seeded.json"
        run("profile", ROOT / "examples/hot_loop.elisa", "--env", "ELISA_RANDOM_SEED=17",
            "--format", "json", "--output", environment_seed_output)
        environment_seeded = json.loads(environment_seed_output.read_text(encoding="utf-8"))
        assert environment_seeded["workload"]["reproducibility"]["random_seed"] == "17"
        assert environment_seeded["workload"]["reproducibility"]["random_seed_source"] == "environment"
        run("profile", ROOT / "examples/hot_loop.elisa", "--random-seed", "42",
            "--env", "ELISA_RANDOM_SEED=17", "--format", "json", ok=False)
        repetitions = measured["run"]["repetitions"]
        assert len(repetitions) == 2
        assert all(
            set(item["detail_records"])
            == {"locations", "functions", "call_edges", "stacks", "thread_loss", "allocation_events"}
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
                "ended",
                "end_event",
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

        target_exit_source = work / "target-exit-126.elisa"
        target_exit_source.write_text(
            "const TARGET_EXIT_CODE: i64 = 126\n\n"
            "def main() -> i64:\n"
            "    return TARGET_EXIT_CODE\n",
            encoding="utf-8",
        )
        target_exit_output = work / "target-exit-126.json"
        run("profile", target_exit_source, "--format", "json", "--output", target_exit_output, expected=TARGET_EXIT_CODE)
        target_exit_report = json.loads(target_exit_output.read_text(encoding="utf-8"))
        assert target_exit_report["run"]["outcome"] == "target_exit"
        assert target_exit_report["run"]["exit_code"] == TARGET_EXIT_CODE
        assert target_exit_report["summary"]["collector_status"] == COLLECTOR_STATUS_OK
        assert target_exit_report["quality"]["capture"] == "target_exit"

        threaded_output = work / "threaded.json"
        run("profile", ROOT / "examples/threaded.elisa", "--format", "json", "--output", threaded_output)
        threaded = json.loads(threaded_output.read_text(encoding="utf-8"))
        assert threaded["summary"]["thread_count"] >= 3
        assert len(threaded["thread_loss"]) >= 3
        assert all(record["repetition"] == 1 for record in threaded["thread_loss"])
        assert all(record["events"] > 0 for record in threaded["thread_loss"])
        assert any(record["ended"] for record in threaded["thread_loss"])
        assert any(not record["ended"] for record in threaded["thread_loss"])
        assert all(record["end_event"] is not None for record in threaded["thread_loss"] if record["ended"])
        assert any(function["function"] == "worker" for function in threaded["functions"])
        assert b"thread loss records: present" in run("report", threaded_output, "--format", "text")
        assert b"Thread loss" in run("report", threaded_output, "--format", "html")

        pipeline_output = work / "multi-module-pipeline.json"
        run("profile", ROOT / "examples/multi_module_pipeline.elisa", "--format", "json",
            "--output", pipeline_output, "--", "--large")
        pipeline = json.loads(pipeline_output.read_text(encoding="utf-8"))
        assert pipeline["workload"]["arguments"] == ["--large"]
        assert pipeline["workload"]["source_tree_sha256"] is not None
        pipeline_functions = {item["function"] for item in pipeline["functions"]}
        assert {"transform", "checksum", "normalize", "mix"}.issubset(pipeline_functions), pipeline_functions
        assert pipeline["summary"]["events"] > 0

        included_output = work / "included-source-map.json"
        run("profile", ROOT / "examples/included_program.elisa", "--format", "json", "--output", included_output)
        included = json.loads(included_output.read_text(encoding="utf-8"))
        assert included["source_mapping"]["mode"] == "compiler-line-map"
        helper_locations = [location for location in included["locations"] if location["function"] == "included_work"]
        assert helper_locations
        assert all(location["source"].endswith("included_helper.elisa") for location in helper_locations)
        assert any(location["line"] != location["compiler_line"] for location in helper_locations)

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

        run("profile", ROOT / "examples/hot_loop.elisa", "--mode", "diagnostic", "--repeat", "2",
            "--format", "json", "--output", output)
        diagnostic_report = json.loads(output.read_text())
        assert diagnostic_report["run"]["collection_mode"] == "diagnostic"
        assert diagnostic_report["run"]["event_trace_enabled"] is True
        diagnostic_repetitions = diagnostic_report["run"]["repetitions"]
        assert len(diagnostic_repetitions) == 2
        diagnostic_events = [event for repetition in diagnostic_repetitions for event in repetition["event_trace"]]
        assert diagnostic_events
        assert all("thread_id" in event and "timestamp_ns" in event for event in diagnostic_events)
        assert {event["repetition"] for event in diagnostic_events} == {1, 2}
        diagnostic_html = run("profile", ROOT / "examples/hot_loop.elisa", "--mode", "diagnostic", "--repeat", "2", "--format", "html")
        assert b"Diagnostic event evidence" in diagnostic_html
        assert b"event-timeline-filter" in diagnostic_html
        assert b"repetition" in diagnostic_html
        mode_comparison = json.loads(run("compare", functions_capture, values_capture, "--format", "json"))
        assert mode_comparison["collection_mode_match"] is False
        assert any("different collection modes" in warning for warning in mode_comparison["warnings"])
        run("profile", ROOT / "examples/hot_loop.elisa", "--mode", "sampling",
            "--sample-period-us", "2000", "--format", "json", "--output", output)
        sampling_alias_report = json.loads(output.read_text())
        assert sampling_alias_report["run"]["collection_mode"] == "sample"
        assert sampling_alias_report["summary"]["sample_period_microseconds"] == 2000
    print("native regression smoke OK")


if __name__ == "__main__":
    main()
