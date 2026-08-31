#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

"$ROOT/scripts/elisa-profiler" profile "$ROOT/examples/hot_loop.elisa" \
    --format json --output "$WORK/report.json"
test -s "$WORK/report.json"

python3 - "$WORK/report.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)

assert report["schema_version"] == 1
assert report["summary"]["events"] > 0
assert report["summary"]["dropped"] == 0
assert report["run"]["exit_code"] == 0
assert report["functions"][0]["function"] == "accumulate"

hot_total = next(
    location["count"]
    for location in report["locations"]
    if location["function"] == "accumulate"
    and location["line"] == 5
    and location["kind"] == "value"
    and location["variable"] == "total"
)
assert hot_total == 10
assert next(
    location["maximum"]
    for location in report["locations"]
    if location["function"] == "accumulate"
    and location["line"] == 5
    and location["kind"] == "value"
    and location["variable"] == "total"
) == 45
print("profiler smoke OK")
PY
