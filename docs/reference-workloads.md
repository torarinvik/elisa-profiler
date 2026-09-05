# Reference workloads

These captures are the M0 baseline for collector and report changes. They are
generated artifacts under the ignored `profiles/reference/` directory, not
fixtures whose timestamps or execution durations should be compared byte for
byte. Tests should compare structural invariants, accounting totals, and
explicit quality fields.

Baseline host: macOS on 2026-09-05.

Compiler provenance:

- dedicated compiler worktree: `../elisa-compiler-worktrees/profiler`
- branch: `codex/profiler`
- commit: `b88dbe6660a6c82d0ad1f915b3ef26ecff1c5df9`
- compiler build manifest SHA-256:
  `678e477bf76ffa18d82aa1d16aefcd09027b729349fff9e58b1fa988e4b5a14d`
- stage1 seed: `-O0`, 8 GiB RSS ceiling
- native target build: `-O0`, `-ftrace -g`

The profiler's native provenance currently reports the compiler worktree as
dirty because the dedicated worktree contains an ignored `.DS_Store`; the
manifest's relevant-source status is clean and its content digest is the
freshness authority. This distinction is intentional and is covered by the
compiler manifest smoke test.

## Hot loop

Command:

```sh
mkdir -p profiles/reference
bin/elisa-profiler profile examples/hot_loop.elisa \
  --format json --repeat 3 --warmup 1 --event-trace \
  --max-event-trace-events 10000 \
  --output profiles/reference/hot-loop.native.json
```

Expected structural facts from the captured run:

- three successful measured repetitions after one warmup
- one traced thread
- no dropped events, call edges, or folded stacks
- complete bounded full traces
- schema version 1
- artifact size: 42 KiB
- SHA-256: `5292214f5e399af9f700846cd069467be17d1f12e0f6010278678cd3e4a656bc`

## Threaded workload

Command:

```sh
bin/elisa-profiler profile examples/threaded.elisa \
  --format json --repeat 2 --warmup 1 \
  --output profiles/reference/threaded.native.json
```

Expected structural facts from the captured run:

- two successful measured repetitions after one warmup
- three traced threads per repetition
- no dropped events, call edges, or folded stacks
- full event tracing disabled, so the trace limit is absent rather than zero
- schema version 1
- artifact size: 13 KiB
- SHA-256: `6fcfa01344a21aee8b5326d55aa43a46440ed6123d8bdd24a25c1cca3f850b54`

Execution duration, memory, and generated binary paths are expected to vary by
host. When a baseline is regenerated, update this file with the new compiler
manifest and artifact hashes, then record the reason in the change commit.
