#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
COMPILER_ROOT="${ELISA_COMPILER_ROOT:-$ROOT/../elisa-compiler-worktrees/profiler}"

if ! git -C "$COMPILER_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    echo "compiler worktree is unavailable or not a git repository: $COMPILER_ROOT" >&2
    exit 2
fi

COMPILER_HEAD="$(git -C "$COMPILER_ROOT" rev-parse HEAD)"
BRANCH_COUNT=0
MISSING_COUNT=0
while read -r REF TIP; do
    BRANCH_COUNT=$((BRANCH_COUNT + 1))
    if ! git -C "$COMPILER_ROOT" merge-base --is-ancestor "$TIP" "$COMPILER_HEAD"; then
        printf 'compiler branch tip is not included: %s (%s)\n' "$REF" "$TIP" >&2
        MISSING_COUNT=$((MISSING_COUNT + 1))
    fi
done < <(git -C "$COMPILER_ROOT" for-each-ref \
    --format='%(refname:short) %(objectname)' refs/heads)

if [[ "$BRANCH_COUNT" -eq 0 ]]; then
    echo "compiler repository has no local branches: $COMPILER_ROOT" >&2
    exit 2
fi
if [[ "$MISSING_COUNT" -ne 0 ]]; then
    printf 'compiler branch audit failed: %s of %s local branch tips are missing from %s\n' \
        "$MISSING_COUNT" "$BRANCH_COUNT" "$COMPILER_HEAD" >&2
    exit 1
fi

printf 'compiler branch audit OK: %s local branch tips included in %s\n' \
    "$BRANCH_COUNT" "$COMPILER_HEAD"

DIRTY_COUNT=0
while IFS= read -r WORKTREE_PATH; do
    if [[ -n "$(git -C "$WORKTREE_PATH" status --porcelain)" ]]; then
        DIRTY_COUNT=$((DIRTY_COUNT + 1))
        printf 'warning: compiler worktree has uncommitted changes: %s\n' "$WORKTREE_PATH" >&2
    fi
done < <(git -C "$COMPILER_ROOT" worktree list --porcelain | sed -n 's/^worktree //p')

if [[ "$DIRTY_COUNT" -ne 0 ]]; then
    printf 'warning: %s compiler worktree(s) contain uncommitted changes; branch audit covers committed tips only\n' \
        "$DIRTY_COUNT" >&2
fi
