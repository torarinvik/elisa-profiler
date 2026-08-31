#!/usr/bin/env python3
"""Verify timeout cleanup terminates forked target descendants."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]


def load_profiler_module():
    loader = SourceFileLoader("elisa_profiler", str(ROOT / "scripts" / "elisa-profiler"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load profiler module")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def main() -> int:
    if os.name != "posix":
        print("process-group smoke SKIP: POSIX process groups unavailable")
        return 0

    profiler = load_profiler_module()
    with tempfile.TemporaryDirectory(prefix="elisa-profiler-process-group-") as directory:
        root = Path(directory)
        child_pid_file = root / "child.pid"
        target = root / "forking-target.sh"
        target.write_text(
            "#!/bin/sh\n"
            "sleep 30 & child=$!\n"
            f'echo "$child" > "{child_pid_file}"\n'
            "while :; do :; done\n",
            encoding="utf-8",
        )
        target.chmod(0o755)

        status, stdout, stderr, timed_out, _ = profiler.execute_program(target, 1.0)
        assert timed_out is True, (status, stdout, stderr)
        assert child_pid_file.is_file(), "target did not launch its child before timeout"
        child_pid = int(child_pid_file.read_text(encoding="utf-8"))
        time.sleep(0.1)
        child_status = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(child_pid)],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        assert not child_status or child_status.startswith("Z"), child_status

    print("process-group cleanup OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
