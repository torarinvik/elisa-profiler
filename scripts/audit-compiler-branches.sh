#!/usr/bin/env bash
set -euo pipefail

# Development-time compiler integration audit. The profiler executable does not
# depend on this script; it records the state used to build that executable.
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
COMPILER_ROOT="${ELISA_COMPILER_ROOT:-$ROOT/../elisa-compiler-worktrees/profiler}"
LEDGER_PATH="${ELISA_COMPILER_LEDGER:-$ROOT/build/compiler-integration-ledger.json}"

if ! git -C "$COMPILER_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    echo "compiler worktree is unavailable or not a git repository: $COMPILER_ROOT" >&2
    exit 2
fi

# Remote refresh is deliberately best effort. A disconnected machine must still
# be able to audit the last fetched refs, but the ledger must make that limitation
# visible instead of presenting cached refs as freshly verified state.
FETCH_ATTEMPTED=0
FETCH_STATUS=0
FETCH_OUTPUT=""
if [[ "${ELISA_COMPILER_AUDIT_FETCH:-1}" == 1 ]]; then
    FETCH_ATTEMPTED=1
    set +e
    FETCH_OUTPUT="$(git -C "$COMPILER_ROOT" fetch --all --prune 2>&1)"
    FETCH_STATUS=$?
    set -e
fi

mkdir -p "$(dirname -- "$LEDGER_PATH")"
LEDGER_DIR="$(cd -- "$(dirname -- "$LEDGER_PATH")" && pwd)"
LEDGER_TMP="$(mktemp "$LEDGER_DIR/.compiler-integration-ledger.XXXXXX")"
cleanup() {
    rm -f "$LEDGER_TMP"
}
trap cleanup EXIT INT TERM HUP

LEDGER_ROOT="$COMPILER_ROOT" \
LEDGER_OUTPUT="$LEDGER_TMP" \
LEDGER_FETCH_ATTEMPTED="$FETCH_ATTEMPTED" \
LEDGER_FETCH_STATUS="$FETCH_STATUS" \
LEDGER_FETCH_OUTPUT="$FETCH_OUTPUT" \
python3 - <<'PY'
import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

root = Path(os.environ["LEDGER_ROOT"]).resolve()
output = Path(os.environ["LEDGER_OUTPUT"])


def run(*args: str) -> tuple[int, str, str]:
    process = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return process.returncode, process.stdout, process.stderr


def git_value(*args: str) -> Optional[str]:
    code, stdout, _ = run(*args)
    value = stdout.strip()
    return value if code == 0 and value else None


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> Optional[str]:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def sha256_json(value: object) -> str:
    return sha256_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def status_records(worktree: Path) -> list[str]:
    process = subprocess.run(
        ["git", "-C", str(worktree), "status", "--porcelain=v1", "--untracked-files=all"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0:
        return [f"<status failed: {process.stderr.strip()}>" ]
    return [line for line in process.stdout.splitlines() if line]


def record_path(record: str) -> str:
    return record[3:] if len(record) >= 4 else record


def is_noise(path: str) -> bool:
    return Path(path).name in {".DS_Store"}


def is_source(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in {
        ".elisa", ".elisai", ".c", ".h", ".cc", ".cpp", ".py", ".sh", ".toml",
    } or Path(path).name in {"Makefile", "CMakeLists.txt"}


def compiler_inputs() -> list[dict[str, Optional[str]]]:
    code, stdout, _ = run(
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
    )
    if code != 0:
        return []
    result = []
    for raw in stdout.encode("utf-8", errors="surrogateescape").split(b"\0"):
        if not raw:
            continue
        relative = os.fsdecode(raw)
        path = root / relative
        if path.name == ".DS_Store" or not path.is_file():
            continue
        result.append({"path": relative, "sha256": sha256_file(path)})
    return sorted(result, key=lambda item: item["path"] or "")


def build_freshness() -> dict:
    inputs = compiler_inputs()
    input_paths = [root / item["path"] for item in inputs if item["path"]]
    stage1 = root / "bin" / "elisac-stage1"
    runtime = root / "build" / "runtime" / "elisacore_runtime.o"
    manifest = root / "build" / "compiler-build-manifest.json"
    reasons = []
    try:
        stage1_mtime = stage1.stat().st_mtime_ns
    except OSError:
        stage1_mtime = None
        reasons.append("stage1 binary is missing")
    try:
        runtime_mtime = runtime.stat().st_mtime_ns
    except OSError:
        runtime_mtime = None
        reasons.append("runtime object is missing")
    newest_input = max((path.stat().st_mtime_ns for path in input_paths if path.is_file()), default=None)
    if stage1_mtime is not None and newest_input is not None and newest_input > stage1_mtime:
        reasons.append("compiler input is newer than stage1 binary")
    manifest_data = None
    if manifest.is_file():
        try:
            with manifest.open(encoding="utf-8") as stream:
                manifest_data = json.load(stream)
        except (OSError, UnicodeError, ValueError):
            reasons.append("compiler build manifest is unreadable")
    else:
        reasons.append("compiler build manifest is missing")
    current_input_sha = sha256_json(inputs)
    manifest_matches = bool(
        isinstance(manifest_data, dict)
        and manifest_data.get("compiler", {}).get("commit") == dedicated_head
        and manifest_data.get("inputs_sha256") == current_input_sha
        and manifest_data.get("stage1", {}).get("sha256") == sha256_file(stage1)
        and manifest_data.get("runtime", {}).get("sha256") == sha256_file(runtime)
    )
    if manifest_data is not None and not manifest_matches:
        reasons.append("compiler build manifest does not match current inputs or artifacts")
    return {
        "manifest": {
            "path": str(manifest),
            "present": manifest.is_file(),
            "sha256": sha256_file(manifest),
            "matches_current_inputs_and_artifacts": manifest_matches,
        },
        "stage1": {"path": str(stage1), "present": stage1.is_file(), "sha256": sha256_file(stage1)},
        "runtime": {"path": str(runtime), "present": runtime.is_file(), "sha256": sha256_file(runtime)},
        "inputs_sha256": current_input_sha,
        "newest_input_mtime_ns": newest_input,
        "stage1_mtime_ns": stage1_mtime,
        "runtime_mtime_ns": runtime_mtime,
        "usable": not reasons,
        "reasons": reasons,
    }


def worktree_inventory(path: Path, head: Optional[str], branch: Optional[str], detached: bool) -> dict:
    records = status_records(path)
    paths = [record_path(record) for record in records]
    relevant = [name for name in paths if not is_noise(name)]
    digest_items = []
    for record, relative in zip(records, paths):
        candidate = path / relative
        digest_items.append({
            "status": record[:2],
            "path": relative,
            "content_sha256": sha256_file(candidate) if candidate.is_file() else None,
        })
    patch_digest = sha256_bytes(
        json.dumps(
            digest_items,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if not records:
        disposition = "clean"
    elif not relevant:
        disposition = "ignored-no-source-delta"
    elif any(is_source(name) for name in relevant):
        disposition = "pending-source-patch"
    else:
        disposition = "pending-non-source-patch"
    return {
        "path": str(path),
        "head": head,
        "branch": branch,
        "detached": detached,
        "dirty": bool(records),
        "status_records": records,
        "dirty_files": paths,
        "relevant_uncommitted_files": relevant,
        "dirty_patch_sha256": patch_digest,
        "disposition": disposition,
    }


def path_subsystems(paths: list[str]) -> list[str]:
    subsystems = set()
    for relative in paths:
        if relative.startswith("src/backend/"):
            subsystems.add("backend")
        elif relative.startswith("src/parser/"):
            subsystems.add("parser")
        elif relative.startswith("src/semantic/"):
            subsystems.add("semantic")
        elif relative.startswith("src/"):
            subsystems.add("compiler-core")
        if relative.startswith("test/"):
            subsystems.add("regression-tests")
    return sorted(subsystems)


def enrich_classification(item: dict) -> None:
    relevant = item["relevant_uncommitted_files"]
    item["affected_subsystems"] = path_subsystems(relevant)
    item["verification_tests"] = [path for path in relevant if path.startswith("test/")]
    if item["disposition"] == "clean":
        item["classification"] = "integrated-or-clean"
        item["review_reason"] = "no uncommitted candidate patch"
        return
    if item["disposition"] == "ignored-no-source-delta":
        item["classification"] = "obsolete-noise-only"
        item["review_reason"] = "desktop metadata is not compiler source"
        return
    if not relevant:
        item["classification"] = "needs-investigation"
        item["review_reason"] = "status exists but no relevant path was resolved"
        return
    dedicated = root
    same_as_dedicated = True
    for relative in relevant:
        candidate = Path(item["path"]) / relative
        destination = dedicated / relative
        if not candidate.is_file() or not destination.is_file() or sha256_file(candidate) != sha256_file(destination):
            same_as_dedicated = False
            break
    if same_as_dedicated:
        item["classification"] = "equivalent-patch"
        item["review_reason"] = "all relevant dirty files match the dedicated worktree; verify origin history before closing"
    elif item["disposition"] == "pending-source-patch":
        item["classification"] = "candidate-fix-needs-review"
        item["review_reason"] = "source differs from the dedicated worktree; review semantics and run affected tests before import"
    else:
        item["classification"] = "candidate-non-source-needs-review"
        item["review_reason"] = "non-source change is not eligible for automatic compiler import"


dedicated_head = git_value("rev-parse", "HEAD")
dedicated_branch = git_value("branch", "--show-current")
if dedicated_head is None:
    raise SystemExit("compiler worktree has no resolvable HEAD")

local_branches = []
code, stdout, _ = run(
    "for-each-ref",
    "--format=%(refname:short)\t%(objectname)",
    "refs/heads",
)
if code != 0:
    raise SystemExit("could not enumerate compiler local branches")
for line in stdout.splitlines():
    if not line.strip():
        continue
    name, tip = line.split("\t", 1)
    included = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", tip, dedicated_head],
        check=False,
    ).returncode == 0
    local_branches.append({
        "name": name,
        "tip": tip,
        "ancestry_included": included,
        "disposition": "integrated" if included else "not-included",
    })

remotes = []
code, stdout, _ = run("remote")
if code == 0:
    for name in [line.strip() for line in stdout.splitlines() if line.strip()]:
        fetch_url = git_value("remote", "get-url", name)
        push_url = git_value("remote", "get-url", "--push", name)
        ref_code, ref_stdout, ref_stderr = run(
            "for-each-ref",
            "--format=%(refname:short)\t%(objectname)",
            f"refs/remotes/{name}",
        )
        refs = []
        if ref_code == 0:
            for line in ref_stdout.splitlines():
                if line.strip():
                    ref_name, tip = line.split("\t", 1)
                    refs.append({"name": ref_name, "tip": tip})
        remotes.append({
            "name": name,
            "fetch_url": fetch_url,
            "push_url": push_url,
            "refs": refs,
            "refs_source": (
                "refreshed"
                if os.environ["LEDGER_FETCH_ATTEMPTED"] == "1"
                and os.environ["LEDGER_FETCH_STATUS"] == "0"
                else "cached"
            ),
            "enumeration_error": ref_stderr.strip() if ref_code else None,
        })

worktrees = []
code, stdout, _ = run("worktree", "list", "--porcelain")
if code == 0:
    current = {}
    for line in stdout.splitlines() + [""]:
        if line.startswith("worktree "):
            current = {"path": Path(line[len("worktree "):]).resolve()}
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):].strip()
        elif line.startswith("branch "):
            ref = line[len("branch "):].strip()
            current["branch"] = ref.removeprefix("refs/heads/")
        elif line == "detached":
            current["detached"] = True
        elif not line and current:
            path = current["path"]
            worktrees.append(worktree_inventory(
                path,
                current.get("head"),
                current.get("branch"),
                bool(current.get("detached", False)),
            ))
            current = {}

for worktree in worktrees:
    enrich_classification(worktree)

dirty_worktrees = [item for item in worktrees if item["dirty"]]
pending_source = [
    item for item in worktrees if item["disposition"] == "pending-source-patch"
]
branch_missing = [item for item in local_branches if not item["ancestry_included"]]
fetch_status = int(os.environ["LEDGER_FETCH_STATUS"])
freshness = build_freshness()
ledger = {
    "format": 2,
    "kind": "elisa_profiler_compiler_integration_ledger",
    "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "host": {"platform": platform.system(), "machine": platform.machine()},
    "dedicated_worktree": {
        "path": str(root),
        "branch": dedicated_branch,
        "head": dedicated_head,
        "source_sha256": sha256_bytes(dedicated_head.encode("ascii")),
    },
    "remote_refresh": {
        "attempted": os.environ["LEDGER_FETCH_ATTEMPTED"] == "1",
        "status": fetch_status,
        "succeeded": fetch_status == 0,
        "output": os.environ["LEDGER_FETCH_OUTPUT"].strip(),
    },
    "local_branches": local_branches,
    "remotes": remotes,
    "worktrees": worktrees,
    "build_freshness": freshness,
    "summary": {
        "local_branch_count": len(local_branches),
        "missing_branch_count": len(branch_missing),
        "worktree_count": len(worktrees),
        "dirty_worktree_count": len(dirty_worktrees),
        "pending_source_worktree_count": len(pending_source),
        "ancestry_complete": not branch_missing,
    },
}

with output.open("w", encoding="utf-8") as stream:
    json.dump(ledger, stream, indent=2, sort_keys=True, ensure_ascii=False)
    stream.write("\n")
PY

mv -f "$LEDGER_TMP" "$LEDGER_PATH"
trap - EXIT INT TERM HUP

BRANCH_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["local_branches"]))' "$LEDGER_PATH")"
MISSING_COUNT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["summary"]["missing_branch_count"])' "$LEDGER_PATH")"
DIRTY_COUNT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["summary"]["dirty_worktree_count"])' "$LEDGER_PATH")"
HEAD="$(git -C "$COMPILER_ROOT" rev-parse HEAD)"

if [[ "$MISSING_COUNT" -ne 0 ]]; then
    echo "compiler branch audit failed: $MISSING_COUNT of $BRANCH_COUNT local branch tips are missing from $HEAD" >&2
    echo "compiler integration ledger: $LEDGER_PATH" >&2
    exit 1
fi

printf 'compiler branch audit OK: %s local branch tips included in %s\n' "$BRANCH_COUNT" "$HEAD"
printf 'compiler integration ledger: %s\n' "$LEDGER_PATH"
if [[ "$FETCH_ATTEMPTED" == 1 && "$FETCH_STATUS" -ne 0 ]]; then
    echo "warning: remote refresh failed; ledger records cached remote refs" >&2
fi
if [[ "$DIRTY_COUNT" -ne 0 ]]; then
    printf 'warning: %s compiler worktree(s) contain uncommitted changes; see ledger dispositions\n' "$DIRTY_COUNT" >&2
fi
