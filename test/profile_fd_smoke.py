#!/usr/bin/env python3
"""Verify collector records are isolated from target stderr."""

from __future__ import annotations

from importlib.machinery import SourceFileLoader
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent.parent
PROFILER = ROOT / "scripts" / "elisa-profiler"


def load_profiler():
    loader = SourceFileLoader("elisa_profiler_fd_test", str(PROFILER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError(f"could not load profiler: {PROFILER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    profiler = load_profiler()
    compiler = os.environ.get("ELISA_CLANG") or shutil.which("clang")
    if compiler is None:
        raise RuntimeError("clang is required for profile FD smoke")
    with tempfile.TemporaryDirectory(prefix="elisa-profile-fd-") as directory:
        root = Path(directory)
        executable = root / "target"
        compile_result = subprocess.run(
            [
                compiler,
                "-std=c11",
                "-O2",
                "-fno-builtin",
                "-pthread",
                "-o",
                str(executable),
                str(ROOT / "scripts" / "profiler_runtime.c"),
                str(ROOT / "test" / "profile_fd_target.c"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert compile_result.returncode == 0, compile_result.stderr

        profile_path = root / "collector.txt"
        status, stdout, stderr, timed_out, _ = profiler.execute_program(
            executable,
            # 30s, not 2: under host memory pressure dyld alone can stall a fresh
            # process for seconds (observed: 0% CPU in _dyld_start while paging), and a
            # tight budget SIGTERMs a correct target mid-startup. A genuine hang still
            # fails; 30s only decides how long that failure takes to report.
            30.0,
            profile_path=profile_path,
        )
        assert status == 0
        assert stdout == b""
        assert not timed_out
        assert "ELISA_PROFILE\t1\tmeta\tspoofed" in stderr.decode(
            "utf-8", errors="replace"
        )
        assert "target diagnostic" in stderr.decode("utf-8", errors="replace")

        collector_text = profile_path.read_text(encoding="utf-8")
        assert "spoofed" not in collector_text
        meta, locations, _, _, collector_stderr, _, _ = profiler.parse_profile(collector_text)
        assert meta["events"] == 32 * 2
        assert len(locations) == 2
        assert meta["thread_count"] >= 2
        assert collector_stderr == ""
    print("profile FD smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
