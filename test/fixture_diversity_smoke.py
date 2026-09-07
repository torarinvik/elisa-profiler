#!/usr/bin/env python3
"""Exercise profiler identity on UTF-8 names and duplicate include basenames."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "examples" / "fixture_diversity.elisa"
TIMEOUT_SECONDS = 120


def main() -> int:
    native = Path(sys.argv[1]) if len(sys.argv) == 2 else ROOT / "bin" / "elisa-profiler"
    with tempfile.TemporaryDirectory(prefix="elisa-profiler-fixture-diversity-") as directory:
        output = Path(directory) / "fixture-diversity.json"
        process = subprocess.run(
            [str(native), "profile", str(SOURCE), "--format", "json", "--output", str(output)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=TIMEOUT_SECONDS,
        )
        if process.returncode != 0:
            raise SystemExit(f"fixture-diversity capture failed: {process.stderr or process.stdout}")
        report = json.loads(output.read_text(encoding="utf-8"))
        if report["run"]["exit_code"] != 0:
            raise SystemExit(f"fixture-diversity target failed: {report['run']}")
        functions = report["functions"]
        names = {record["function"] for record in functions}
        if "café" not in names:
            raise SystemExit(f"UTF-8 function identity was lost: {sorted(names)!r}")
        workers = [record for record in functions if record["function"] == "worker"]
        worker_ids = {record.get("identity_id") for record in workers}
        if len(workers) != 2 or len(worker_ids) != 2 or None in worker_ids:
            raise SystemExit(f"duplicate-basename module identities were merged: {workers!r}")
        edge_ids = {
            edge.get("callee_id")
            for edge in report["call_edges"]
            if edge["callee"] == "worker"
        }
        if edge_ids != worker_ids:
            raise SystemExit(f"caller-edge identities lost module distinction: {edge_ids!r}")
    print("fixture diversity smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
