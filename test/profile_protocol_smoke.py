#!/usr/bin/env python3
"""Verify graceful handling of malformed collector protocol records."""

from __future__ import annotations

from importlib.machinery import SourceFileLoader
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PROFILER = ROOT / "scripts" / "elisa-profiler-legacy.py"


def load_profiler():
    loader = SourceFileLoader("elisa_profiler_protocol_test", str(PROFILER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError(f"could not load profiler: {PROFILER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_malformed(profiler, record: str) -> None:
    try:
        profiler.parse_profile(record)
    except profiler.ProfilerError as error:
        assert str(error).startswith("malformed profiler runtime record:")
    else:
        raise AssertionError("malformed protocol record was accepted")


def assert_unsupported_version(profiler, record: str) -> None:
    try:
        profiler.parse_profile(record)
    except profiler.ProfilerError as error:
        assert str(error).startswith("unsupported profiler runtime protocol version:")
    else:
        raise AssertionError("unsupported protocol version was accepted")


def main() -> int:
    profiler = load_profiler()
    extended_meta = profiler.parse_profile(
        "ELISA_PROFILE\t1\tmeta\t64\t2\t3\t4\t5\t6\t7\t8\t9\t1\t10\t11\t1024\t512\t64"
    )[0]
    assert extended_meta["location_limit"] == 7
    assert extended_meta["call_edge_limit"] == 8
    assert extended_meta["stack_limit"] == 9
    assert extended_meta["budget_exceeded"] == 1
    assert extended_meta["call_edge_dropped"] == 10
    assert extended_meta["stack_dropped"] == 11
    assert extended_meta["capture_byte_limit"] == 1024
    assert extended_meta["capture_bytes_used"] == 512
    assert extended_meta["capture_bytes_dropped"] == 64
    assert_unsupported_version(profiler, "ELISA_PROFILE\t2\tmeta\t0\t0\t0")
    assert_malformed(profiler, "ELISA_PROFILE\t1\tmeta\tnot-a-number\t0\t0")
    assert_malformed(profiler, "ELISA_PROFILE\t1\tmeta\t-1\t0\t0")
    assert_malformed(profiler, "ELISA_PROFILE\t1\tmeta\t18446744073709551616\t0\t0")
    assert_malformed(
        profiler,
        "ELISA_PROFILE\t1\tlocation\t1\tmain\tnot-a-line\t1\t-\t0\t0\t0\t0\t0\t0\t0",
    )
    assert_malformed(
        profiler,
        "ELISA_PROFILE\t1\tlocation\t3\tmain\t1\t1\t-\t0\t-1\t0\t0\t0\t0\t0",
    )
    assert_malformed(
        profiler,
        "ELISA_PROFILE\t1\tlocation\t2\tmain\t1\t1\tvalue\t1\t9223372036854775808\t0\t0\t0\t0\t0",
    )
    empty = profiler.parse_profile("target wrote no collector records\n", allow_missing=True)
    assert empty[0]["events"] == 0
    assert empty[3] == []
    print("profile protocol smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
