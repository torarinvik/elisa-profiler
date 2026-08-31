# Elisa profiler

This repository will contain a profiler for programs written in Elisa.

The profiler uses a dedicated local worktree of the self-hosted compiler so
compiler changes stay isolated from the main compiler checkout and can be
committed independently when profiling exposes a compiler bug.

## Local compiler

The default compiler worktree is:

```text
../elisa-compiler-worktrees/profiler
```

It is checked out from the compiler repository's `work` branch on
`codex/profiler`. The profiler-side wrapper resolves that worktree by default;
override it with `ELISA_COMPILER_ROOT` when needed.

```sh
make compiler-status
make compiler-seed
make compiler-smoke
make profiler-smoke
make test

scripts/elisa-compiler -o build/hello.o examples/hello.elisa
```

`compiler-seed` uses the local stage0 compiler at
`../../Go projects/structpy-tree` by default. Set `STAGE0_CORE` or
`ELISA_STAGE0_CORE` when using a different local stage0 checkout. The seeded
stage1 binary and compiler build outputs remain ignored artifacts inside the
compiler worktree.

The profiler Makefile seeds at -O0 with an 8 GiB RSS cap by default for a
predictable local bootstrap. Override SEED_OPT_LEVEL and SEED_MAX_RSS_KB when
the host has more headroom.

## Profiling direction

The first implementation milestone is to compile and run an Elisa target with
source-aware measurements, then report those measurements by function and
source location. Compiler instrumentation and runtime event-format changes
will live in the dedicated compiler worktree; the profiler repository will own
the command-line interface, collection, and report formats.

## Profile a program

The profiler expects an Elisa source file with main() -> i64. It compiles with
the local stage1 compiler using -ftrace -g, links a small host collector, runs
the program, and reports statement/value events:

    scripts/elisa-profiler profile examples/hot_loop.elisa
    scripts/elisa-profiler examples/hot_loop.elisa --format json -o profiles/hot-loop.json

The text report lists hot source locations and event totals. JSON reports have
schema version 1, compiler provenance, execution status/timing, all locations
with source snippets, and scalar value statistics (minimum, maximum, sum, and
last). Include-expanded programs are mapped back to the file and line where
each location originated; compiler_line preserves the flattened line for
diagnostics. A nonzero target exit status is reported and returned by the
profiler. Use --show-output to forward the target's stdout/stderr.

Useful controls:

    --opt-level 0..3       choose the compiler optimization level (default: 0)
    --top N                number of locations in the text report (default: 20)
    --warmup N             execute N unreported startup runs (default: 0)
    --repeat N             execute and merge N measured runs (default: 1)
    --timeout SECONDS      terminate a runaway execution and retain its partial report
    --compiler-root PATH   use another isolated compiler worktree
    --rebuild-runtime      rebuild the selected compiler runtime object
    --keep-temp            retain generated objects and the linked executable

The runtime collector uses the backend's complete-run trace callbacks, rather
than the runtime's bounded crash-debug ring, so loop counts are not truncated to
the last 256 events. The first profiler ABI is intentionally for main() with no
arguments; richer argument/benchmark control can be added without changing the
report schema. Repeated runs stop after the first nonzero target status and the
report retains every completed repetition. The measurements are event counts
and wall-clock process timings, not statistical CPU samples. Panics and timed-out
children retain their partial trace when the process reaches the collector's
exit/signal handler.
