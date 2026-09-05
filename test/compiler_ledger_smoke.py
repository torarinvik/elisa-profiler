#!/usr/bin/env python3
"""Validate the compiler integration ledger emitted by compiler-audit."""

from __future__ import annotations

import json
import sys
from pathlib import Path


EXPECTED_FORMAT = 2
REQUIRED_SUMMARY_KEYS = {
    "local_branch_count",
    "missing_branch_count",
    "worktree_count",
    "dirty_worktree_count",
    "pending_source_worktree_count",
    "ancestry_complete",
}
REQUIRED_WORKTREE_KEYS = {
    "path",
    "head",
    "branch",
    "dirty",
    "dirty_files",
    "relevant_uncommitted_files",
    "dirty_patch_sha256",
    "disposition",
    "classification",
    "affected_subsystems",
    "verification_tests",
    "review_reason",
}


def fail(message: str) -> None:
    raise SystemExit(f"compiler ledger smoke failed: {message}")


def main() -> int:
    if len(sys.argv) != 2:
        fail("usage: compiler_ledger_smoke.py LEDGER.json")
    path = Path(sys.argv[1])
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        fail(f"cannot read {path}: {error}")
    if not isinstance(document, dict):
        fail("top-level value is not an object")
    if document.get("kind") != "elisa_profiler_compiler_integration_ledger":
        fail("unexpected kind")
    if document.get("format") != EXPECTED_FORMAT:
        fail(f"expected format {EXPECTED_FORMAT}")
    required = {
        "observed_at_utc",
        "dedicated_worktree",
        "remote_refresh",
        "local_branches",
        "remotes",
        "worktrees",
        "summary",
        "build_freshness",
    }
    for key in required:
        if key not in document:
            fail(f"missing top-level key {key}")
    summary = document["summary"]
    if not isinstance(summary, dict) or not REQUIRED_SUMMARY_KEYS.issubset(summary):
        fail("summary is incomplete")
    branches = document["local_branches"]
    if not isinstance(branches, list) or not branches:
        fail("local branch inventory is empty")
    if any(not isinstance(item, dict) for item in branches):
        fail("local branch inventory contains a non-object")
    if summary["local_branch_count"] != len(branches):
        fail("local branch count does not match inventory")
    if summary["missing_branch_count"] != sum(
        not item.get("ancestry_included", False) for item in branches
    ):
        fail("missing branch count does not match ancestry flags")
    worktrees = document["worktrees"]
    if not isinstance(worktrees, list) or not worktrees:
        fail("worktree inventory is empty")
    for item in worktrees:
        if not isinstance(item, dict) or not REQUIRED_WORKTREE_KEYS.issubset(item):
            fail("worktree inventory entry is incomplete")
        if item["dirty"] != bool(item["dirty_files"]):
            fail(f"dirty flag disagrees with files for {item['path']}")
        if not set(item["relevant_uncommitted_files"]).issubset(item["dirty_files"]):
            fail(f"relevant files are not a subset for {item['path']}")
    if summary["worktree_count"] != len(worktrees):
        fail("worktree count does not match inventory")
    if summary["dirty_worktree_count"] != sum(item["dirty"] for item in worktrees):
        fail("dirty worktree count does not match inventory")
    refresh = document["remote_refresh"]
    refresh_keys = {"attempted", "status", "succeeded", "output"}
    if not isinstance(refresh, dict) or not refresh_keys.issubset(refresh):
        fail("remote refresh record is incomplete")
    if refresh["succeeded"] != (refresh["status"] == 0):
        fail("remote refresh success does not match status")
    freshness = document["build_freshness"]
    freshness_keys = {"manifest", "stage1", "runtime", "inputs_sha256", "usable", "reasons"}
    if not isinstance(freshness, dict) or not freshness_keys.issubset(freshness):
        fail("build freshness record is incomplete")
    if freshness["usable"] != (not freshness["reasons"]):
        fail("build freshness status does not match reasons")
    if not isinstance(freshness["manifest"], dict) or not {"path", "present", "matches_current_inputs_and_artifacts"}.issubset(freshness["manifest"]):
        fail("build manifest freshness record is incomplete")
    print(f"compiler ledger smoke OK: {len(branches)} branches, {len(worktrees)} worktrees")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
