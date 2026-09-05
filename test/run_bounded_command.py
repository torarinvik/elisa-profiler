#!/usr/bin/env python3
"""Run one smoke command with a process-group timeout.

The native executable can fork a target, so a timeout must terminate the whole
command group rather than only the launcher process. This is test infrastructure;
the profiler implementation itself remains Elisa-native.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys


TIMEOUT_ENVIRONMENT_VARIABLE = "ELISA_NATIVE_COMMAND_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 30.0
TIMEOUT_EXIT_STATUS = 124


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: run_bounded_command.py COMMAND [ARGUMENT ...]")
    timeout_seconds = float(
        os.environ.get(TIMEOUT_ENVIRONMENT_VARIABLE, str(DEFAULT_TIMEOUT_SECONDS))
    )
    if timeout_seconds <= 0:
        raise SystemExit(f"{TIMEOUT_ENVIRONMENT_VARIABLE} must be positive")

    process = subprocess.Popen(sys.argv[1:], start_new_session=(os.name == "posix"))
    try:
        return process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait()
        command = " ".join(sys.argv[1:])
        print(
            f"bounded smoke command timed out after {timeout_seconds:g}s: {command}",
            file=sys.stderr,
        )
        return TIMEOUT_EXIT_STATUS


if __name__ == "__main__":
    raise SystemExit(main())
