#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

(cd /tmp && ELISA_NATIVE_COMMAND_TIMEOUT_SECONDS=10 \
    python3 "$ROOT/test/run_bounded_command.py" \
    "$ROOT/bin/elisa-profiler" doctor --format json --output "$WORK/doctor.json")

grep -Fq '"ok":true' "$WORK/doctor.json"
grep -Fq '"compiler_manifest":true' "$WORK/doctor.json"
echo "bootstrap path smoke OK"
