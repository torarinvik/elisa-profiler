#!/usr/bin/env python3
"""Reject a source edit that occurs between hashing and target compilation."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
TIMEOUT_SECONDS = 30


def run_profile(profiler: Path, arguments: list[str], environment: dict[str, str]) -> tuple[int, str, str]:
    process = subprocess.Popen(
        [str(profiler), *arguments],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=(os.name == "posix"),
    )
    try:
        stdout, stderr = process.communicate(timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.communicate()
        raise AssertionError("source stability smoke timed out") from error
    return process.returncode, stdout, stderr


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: source_stability_smoke.py NATIVE_PROFILER")
    profiler = Path(sys.argv[1]).resolve()
    compiler = (ROOT / "../elisa-compiler-worktrees/profiler/bin/elisac-stage1").resolve()
    with tempfile.TemporaryDirectory(prefix="elisa-source-stability-") as directory:
        work = Path(directory)
        source = work / "target.elisa"
        output = work / "report.json"
        source.write_text("def main() -> i64:\n    return 1\n", encoding="utf-8")
        wrapper = work / "mutating-stage1.py"
        wrapper.write_text(
            "#!/usr/bin/env python3\n"
            "import os\n"
            "from pathlib import Path\n"
            "import sys\n"
            f"source = Path(sys.argv[-1])\n"
            "source.write_text('def main() -> i64:\\n    return 0\\n', encoding='utf-8')\n"
            f"compiler = {str(compiler)!r}\n"
            "os.execv(compiler, [compiler, *sys.argv[1:]])\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        environment = os.environ.copy()
        environment["ELISA_STAGE1_BIN"] = str(wrapper)
        status, stdout, stderr = run_profile(
            profiler,
            ["profile", str(source), "--format", "json", "--output", str(output)],
            environment,
        )
        assert status == 2, (status, stdout, stderr)
        assert "source changed while the target was compiling" in stderr, stderr
        assert not output.exists(), output

        mutation_source = work / "mutation-target.elisa"
        mutation_source.write_text(
            (ROOT / "examples" / "native_source_mutation_probe.elisa").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        mutation_output = work / "mutation-report.json"
        mutation_environment = os.environ.copy()
        mutation_environment["ELISA_SOURCE_MUTATION_PATH"] = str(mutation_source)
        status, stdout, stderr = run_profile(
            profiler,
            [
                "profile",
                str(mutation_source),
                "--env",
                f"ELISA_SOURCE_MUTATION_PATH={mutation_source}",
                "--format",
                "json",
                "--output",
                str(mutation_output),
            ],
            mutation_environment,
        )
        assert status == 2, (status, stdout, stderr)
        assert "source changed during profiling" in stderr, stderr
        assert not mutation_output.exists(), mutation_output
    print("source stability smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
