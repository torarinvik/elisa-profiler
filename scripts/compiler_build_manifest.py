#!/usr/bin/env python3
"""Write or validate the ignored manifest for the local Elisa compiler build.

This is build/audit plumbing only. The native profiler does not import this module
at runtime; it records the manifest as provenance when it is compiled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Optional


MANIFEST_FORMAT = 1
SOURCE_SUFFIXES = {".elisa", ".elisai", ".c", ".h", ".cc", ".cpp"}
TOOL_NAMES = ("clang", "llvm-config", "llvm-objcopy", "llvm-nm")


def run(command: list[str], cwd: Optional[Path] = None) -> tuple[int, str, str]:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, result.stdout, result.stderr


def git(root: Path, *arguments: str) -> tuple[int, str, str]:
    return run(["git", "-C", str(root), *arguments])


def git_value(root: Path, *arguments: str) -> Optional[str]:
    code, stdout, _ = git(root, *arguments)
    value = stdout.strip()
    return value if code == 0 and value else None


def sha256_stream(stream: Any) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> Optional[str]:
    try:
        with path.open("rb") as stream:
            return sha256_stream(stream)
    except OSError:
        return None


def sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def tracked_inputs(root: Path) -> list[Path]:
    code, stdout, _ = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if code != 0:
        return []
    paths = []
    for raw in stdout.encode("utf-8", errors="surrogateescape").split(b"\0"):
        if not raw:
            continue
        relative = os.fsdecode(raw)
        path = root / relative
        if path.name != ".DS_Store" and path.is_file():
            paths.append(path)
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def input_records(root: Path, paths: Iterable[Path]) -> list[dict[str, Any]]:
    records = []
    for path in paths:
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            relative = str(path)
        records.append({
            "path": relative,
            "sha256": sha256_file(path),
        })
    return records


def status_records(root: Path) -> list[str]:
    code, stdout, stderr = git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if code != 0:
        return [f"<status failed: {stderr.strip()}>" ]
    return [line for line in stdout.splitlines() if line]


def status_digest(records: list[str]) -> str:
    return hashlib.sha256("\n".join(records).encode("utf-8")).hexdigest()


def tool_info(root: Path) -> dict[str, Any]:
    llvm_config_name = os.environ.get("LLVM_CONFIG", "llvm-config")
    configured = {
        "clang": os.environ.get("ELISA_CLANG", "clang"),
        "llvm_config": llvm_config_name,
        "objcopy": os.environ.get("ELISA_OBJCOPY", "llvm-objcopy"),
        "nm": os.environ.get("ELISA_NM", "llvm-nm"),
    }
    result: dict[str, Any] = {}
    for key, name in configured.items():
        resolved = name if os.path.isabs(name) else shutil.which(name)
        record: dict[str, Any] = {"requested": name, "path": resolved}
        if resolved:
            code, stdout, _ = run([resolved, "--version"])
            record["version"] = (stdout.splitlines()[0].strip() if code == 0 and stdout else "unknown")
            record["sha256"] = sha256_file(Path(resolved))
            if key == "llvm_config":
                _, libdir, _ = run([resolved, "--libdir"])
                record["libdir"] = libdir.strip() or None
        result[key] = record
    return result


def runtime_abi(runtime_object: Path) -> dict[str, Any]:
    nm = os.environ.get("ELISA_NM", "llvm-nm")
    resolved = nm if os.path.isabs(nm) else shutil.which(nm)
    if not resolved or not runtime_object.is_file():
        return {"available": False, "trace_symbols": []}
    code, stdout, _ = run([resolved, "-g", str(runtime_object)])
    if code != 0:
        return {"available": False, "trace_symbols": []}
    symbols = []
    for line in stdout.splitlines():
        fields = line.split()
        if not fields:
            continue
        symbol = fields[-1].lstrip("_")
        if symbol.startswith("elisa_trace_"):
            symbols.append(symbol)
    symbols = sorted(set(symbols))
    return {
        "available": bool(symbols),
        "trace_symbols": symbols,
        "capabilities": {
            "function_entry_exit": (
                "elisa_trace_function_entry" in symbols
                and "elisa_trace_function_exit" in symbols
            ),
            "statement_events": "elisa_trace_pos" in symbols,
            "scalar_events": "elisa_trace_record_value" in symbols,
            "compiler_stable_ids": (
                "elisa_trace_record_id" in symbols
                and "elisa_trace_record_value_id" in symbols
                and "elisa_trace_function_entry_id" in symbols
                and "elisa_trace_function_exit_id" in symbols
            ),
            "fault_capture": "elisa_trace_install_fault_handler" in symbols,
        },
    }


def newest_mtime(paths: Iterable[Path]) -> Optional[int]:
    newest: Optional[int] = None
    for path in paths:
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            continue
        newest = mtime if newest is None else max(newest, mtime)
    return newest


def build_document(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.compiler_root).resolve()
    stage1 = Path(args.stage1).resolve()
    runtime = Path(args.runtime).resolve()
    inputs = input_records(root, tracked_inputs(root))
    records = status_records(root)
    relevant_records = [
        record for record in records
        if Path(record[3:] if len(record) >= 4 else record).name != ".DS_Store"
    ]
    dirty_source_items = []
    for record in relevant_records:
        relative = record[3:] if len(record) >= 4 else record
        if Path(relative).suffix.lower() in SOURCE_SUFFIXES or relative.startswith(("src/", "elisacore_std/")):
            dirty_source_items.append({
                "status": record[:2],
                "path": relative,
                "sha256": sha256_file(root / relative),
            })
    dirty_source_sha256 = sha256_json(dirty_source_items)
    source_paths = [
        root / relative
        for relative in (record["path"] for record in inputs)
        if Path(relative).suffix.lower() in SOURCE_SUFFIXES
        or relative.startswith("src/")
        or relative.startswith("elisacore_std/")
    ]
    source_records = [
        record for record in inputs
        if Path(record["path"]).suffix.lower() in SOURCE_SUFFIXES
        or record["path"].startswith("src/")
        or record["path"].startswith("elisacore_std/")
    ]
    stage0 = Path(args.stage0).resolve() if args.stage0 else None
    tools = tool_info(root)
    abi = runtime_abi(runtime)
    stage1_mtime = stage1.stat().st_mtime_ns if stage1.is_file() else None
    runtime_mtime = runtime.stat().st_mtime_ns if runtime.is_file() else None
    newest_input = newest_mtime(source_paths)
    runtime_paths = [
        path for path in source_paths
        if path.is_relative_to(root / "elisacore_std")
    ] if hasattr(Path, "is_relative_to") else [
        path for path in source_paths if str(path).startswith(str(root / "elisacore_std") + os.sep)
    ]
    newest_runtime_input = newest_mtime(runtime_paths + [root / "scripts" / "build_runtime_object.sh"])
    freshness_reasons = []
    if not stage1.is_file():
        freshness_reasons.append("stage1 binary is missing")
    elif newest_input is not None and stage1_mtime is not None and newest_input > stage1_mtime:
        freshness_reasons.append("compiler source/configuration is newer than stage1 binary")
    if not runtime.is_file():
        freshness_reasons.append("runtime object is missing")
    elif newest_runtime_input is not None and runtime_mtime is not None and newest_runtime_input > runtime_mtime:
        freshness_reasons.append("runtime source/build script is newer than runtime object")
    stage0_hash = sha256_file(stage0) if stage0 else None
    identity_inputs = {
        "compiler_commit": git_value(root, "rev-parse", "HEAD"),
        "dirty_status_sha256": status_digest(relevant_records),
        "dirty_source_sha256": dirty_source_sha256,
        "inputs": inputs,
        "stage0": {"path": str(stage0) if stage0 else None, "sha256": stage0_hash},
        "seed": {
            "driver": str(root / "src" / "driver" / "elisac.elisa"),
            "optimization": args.seed_opt_level,
            "max_rss_kb": args.seed_max_rss_kb,
            "script_sha256": sha256_file(root / "scripts" / "elisac_stage1.sh"),
        },
        "tools": tools,
        "architecture": {"system": platform.system(), "machine": platform.machine()},
        "abi": abi,
    }
    return {
        "format": MANIFEST_FORMAT,
        "kind": "elisa_profiler_compiler_build_manifest",
        "generated_by": "scripts/compiler_build_manifest.py",
        "compiler": {
            "root": str(root),
            "branch": git_value(root, "branch", "--show-current"),
            "commit": identity_inputs["compiler_commit"],
            "dirty": bool(relevant_records),
            "dirty_files": [record[3:] for record in records if len(record) >= 4],
            "relevant_dirty_files": [record[3:] for record in relevant_records if len(record) >= 4],
            "dirty_status_sha256": identity_inputs["dirty_status_sha256"],
            "dirty_source_sha256": dirty_source_sha256,
        },
        "inputs_sha256": sha256_json(inputs),
        "source_sha256": sha256_json(source_records),
        "seed_identity": sha256_json(identity_inputs),
        "stage0": identity_inputs["stage0"],
        "stage1": {"path": str(stage1), "sha256": sha256_file(stage1)},
        "runtime": {"path": str(runtime), "sha256": sha256_file(runtime)},
        "build_flags": {
            "seed_optimization": args.seed_opt_level,
            "seed_max_rss_kb": args.seed_max_rss_kb,
            "native_optimization": args.native_opt_level,
            "trace": True,
            "debug_info": True,
        },
        "toolchain": tools,
        "architecture": {"system": platform.system(), "machine": platform.machine()},
        "abi": abi,
        "freshness": {
            "usable": not freshness_reasons,
            "reasons": freshness_reasons,
            "newest_compiler_input_mtime_ns": newest_input,
            "stage1_mtime_ns": stage1_mtime,
            "newest_runtime_input_mtime_ns": newest_runtime_input,
            "runtime_mtime_ns": runtime_mtime,
        },
        "identity": identity_inputs,
    }


def write_atomic(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler-root", required=True)
    parser.add_argument("--stage1", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--stage0")
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed-opt-level", default="unknown")
    parser.add_argument("--seed-max-rss-kb", default="unknown")
    parser.add_argument("--native-opt-level", default="-O0")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.output).resolve()
    document = build_document(args)
    if args.check:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            print(f"compiler build manifest missing or invalid: {path}", file=sys.stderr)
            return 1
        if existing.get("seed_identity") != document.get("seed_identity"):
            print("compiler build manifest identity is stale", file=sys.stderr)
            return 1
        if existing.get("stage1") != document.get("stage1") or existing.get("runtime") != document.get("runtime"):
            print("compiler build manifest artifact hash is stale", file=sys.stderr)
            return 1
        if not document["freshness"]["usable"]:
            print("compiler build is stale: " + "; ".join(document["freshness"]["reasons"]), file=sys.stderr)
            return 1
        print(f"compiler build manifest current: {path}")
        return 0
    write_atomic(path, document)
    state = "usable" if document["freshness"]["usable"] else "stale"
    print(f"compiler build manifest written ({state}): {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
