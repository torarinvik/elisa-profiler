# Elisa profiler

This repository contains a profiler for programs written in Elisa.

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
make compiler-audit
make compiler-ledger-smoke
make compiler-seed
make compiler-smoke
make runtime-abi-smoke
make profiler-native-smoke
make test

scripts/elisa-compiler -o build/hello.o examples/hello.elisa
```

`compiler-seed` uses `ELISACORE_BIN` when it is set, then the local
`elisac-stage0` on `PATH`, and finally the documented sibling stage0 checkout at
`../../Go projects/structpy-tree`. Set `STAGE0_CORE` or `ELISA_STAGE0_CORE` when
using a different local stage0 checkout. The seeded stage1 binary and compiler
build outputs remain ignored artifacts inside the compiler worktree.

`compiler-audit` verifies that every local branch tip in the compiler repository is
already included in the profiler compiler worktree and atomically writes the ignored
`build/compiler-integration-ledger.json` inventory. The ledger records remote refresh
status, worktree HEADs, dirty files, relevant untracked files, and dirty-patch
digests. It also warns about uncommitted changes in any compiler worktree; those
changes are intentionally not imported until they have been reviewed and committed.
`compiler-ledger-smoke` validates that inventory before the broader test gate runs.
After a successful seed, `compiler-manifest-smoke` validates the ignored compiler
build manifest, including content-based input identity, artifact hashes, toolchain,
architecture, and trace ABI capabilities. A failed seed cannot replace the last
usable stage1 binary because seed outputs are published atomically.

The profiler Makefile seeds at -O0 with an 8 GiB RSS cap by default for a
predictable local bootstrap. Override SEED_OPT_LEVEL and SEED_MAX_RSS_KB when
the host has more headroom.

## Profiling direction

The first implementation milestone is to compile and run an Elisa target with
source-aware measurements, then report those measurements by function and
source location. Compiler instrumentation and runtime event-format changes
will live in the dedicated compiler worktree; the profiler repository will own
the command-line interface, collection, and report formats.

The canonical implementation is Elisa. The native executable is built with
`make profiler-native` and exercised with `make profiler-native-smoke`; its
`ProfilerNative` module exposes only a public `run` entry point and keeps
implementation helpers private. Invoke the built executable directly as
`bin/elisa-profiler`. The former Python implementation has been removed; no
user-facing command dispatches through a second profiler implementation. The
native executable resolves
defaults for the dedicated compiler worktree, runtime object, and collector
source relative to its own location, so it is safe to invoke from outside the
repository directory.

The native build pipeline passes compiler, object-copy, collector, linker, and
Git metadata operations through direct argument vectors. It does not construct
shell command strings for the normal profiling path, so paths and user-selected
tool overrides are never re-parsed by a shell.

Native profiles currently support JSON, text, folded-stack, Speedscope sampled,
and HTML output. The native `report` command preserves JSON captures and can
regenerate text, folded-stack, Speedscope, and HTML artifacts offline;
the native `compare` command emits schema-validated summary deltas and explicit
warnings for mismatched or incomplete evidence.

The native launcher also accepts `--cwd PATH`, `--stdin PATH`, repeatable
`--env KEY=VALUE` controls, and a `--` separator followed by verbatim target
arguments. These are applied only to the profiled child and are exercised by
the native launch probes. The collector wrapper passes `argc`/`argv` to
argv-aware Elisa targets while remaining compatible with the legacy
`main() -> i64` entry form. Native JSON captures also preserve the source size,
launch directory, stdin path, environment-key names, and exact target argument
vector as workload metadata.
Each native capture also records host provenance when the platform exposes it:
`uname` OS/architecture, a one-minute load-average sample, inherited affinity
policy, and an explicit null for power/thermal telemetry that is unavailable.
The launcher never changes machine-wide affinity or power settings.

## Profile a program

The profiler expects an Elisa source file with main() -> i64. It compiles with
the local stage1 compiler using -ftrace -g, links a small host collector, runs
the program, and reports function-entry, statement, and scalar-value events:

    bin/elisa-profiler profile examples/hot_loop.elisa
    bin/elisa-profiler profile examples/hot_loop.elisa --format json -o profiles/hot-loop.json
    bin/elisa-profiler profile examples/hot_loop.elisa --format folded \
        -o profiles/hot-loop.folded
    bin/elisa-profiler profile examples/hot_loop.elisa --format speedscope \
        -o profiles/hot-loop.speedscope.json
    bin/elisa-profiler profile examples/hot_loop.elisa --format html \
        -o profiles/hot-loop.html
    bin/elisa-profiler profile examples/hot_loop.elisa --mode functions --format json \
        -o profiles/hot-loop-functions.json
    bin/elisa-profiler profile examples/hot_loop.elisa --mode diagnostic --format html \
        -o profiles/hot-loop-diagnostic.html
    bin/elisa-profiler profile examples/hot_loop.elisa --progress profiles/hot-loop.progress.json \
        --format json -o profiles/hot-loop.json
    bin/elisa-profiler report profiles/hot-loop.json --format html \
        -o profiles/hot-loop.html
    bin/elisa-profiler recover profiles/hot-loop.json.manifest.json \
        --format json -o profiles/hot-loop-recovered.json
    bin/elisa-profiler doctor
    bin/elisa-profiler compare profiles/baseline.json profiles/candidate.json
    bin/elisa-profiler compare profiles/baseline.json profiles/candidate.json \
        --format html -o profiles/comparison.html
    bin/elisa-profiler compare profiles/baseline.json profiles/candidate.json \
        --max-wall-regression-percent 5 --max-wall-ms 250

The default `full` mode records function, statement, and scalar-value events.
`functions` keeps function/call-path evidence, `statements` keeps statement
and function evidence, and `values` keeps scalar values plus function context.
`diagnostic` enables the bounded event trace in addition to full instrumentation.
Sampling is not claimed by this instrumented build; an explicit sampling mode
request fails with an actionable error. The selected mode is recorded in
`run.collection_mode` and shown by text/HTML reports. JSON also records
`run.capabilities`, including retained event classes, trace/path policy, wall
timing, the unsupported sampling status, and the active detail limits.

The text report lists the structured run outcome, capture completeness, hot
source locations, and event totals. HTML summary cards additionally show the
source SHA-256, host identity, inherited-affinity policy, explicit thermal
availability, and the same completeness classification. JSON reports have
schema version 1, compiler provenance, selected optimization level,
execution status/timing, all locations
with source snippets, function call-event counts, aggregate caller-to-callee
edges, folded call stacks, and scalar value statistics
(minimum, maximum, sum, and last). Signed scalar values retain their signed
interpretation instead of being reported as raw u64 bit patterns.
The summary includes the number of distinct threads that emitted trace events,
which makes worker activity visible in threaded targets.
Native JSON also includes per-capture `thread_loss` records with repetition
identity and per-thread detail/trace-drop counters; text and HTML reports expose
the same diagnostics for offline inspection.
The machine-readable contract is published at
[`docs/profile.schema.json`](docs/profile.schema.json).
Use `--progress PATH` for an atomic machine-readable status snapshot on a
separate channel; its contract and stage semantics are documented in
[`docs/progress.md`](docs/progress.md).
Use `--path-map FROM=TO` to replace one boundary-aware source-path prefix in
report display fields; the raw path remains in the local capture manifest for
recovery. See [`docs/path-remapping.md`](docs/path-remapping.md).
Pass `--embed-source` when a portable JSON report should carry the exact source
bytes used for the capture; the snapshot includes its SHA-256 digest and is
opt-in because it can make reports substantially larger.
Compiler provenance includes the stage1 and runtime object hashes, source
status digest and dirty-file list, host/toolchain information, profiling build
options, and the content fingerprint used to validate the cached runtime
object. A report therefore identifies both the compiler checkout and the
actual binaries used to produce the capture.
Function timing also includes mean inclusive/self duration and percentages of
the root function's inclusive time, so the JSON report is useful without a
separate post-processing step.
Native reports use the collector's wall-clock interval attribution and rank
locations, functions, and call-graph edges using the observed duration when it
is available; count fields remain explicit for count-only evidence.
Each measured repetition records child user/system CPU time and peak resident
set size from the native `wait4` resource result when the host provides it;
aggregate CPU time is kept separate from wall-clock execution time.
Each repetition also records its trace event/location totals, traced-thread
count, dropped-event count, and stack-depth diagnostics, so merged reports can
be audited run by run.
Aggregate timing and resource statistics use only successful repetitions when
at least one exists; failed repetitions remain available with their partial
trace data and explicit status.
The run's `measurement_basis` and `measurement_repetitions` fields make that
choice explicit; an `all_completed` basis means every completed repetition
failed, so its aggregates are retained only as partial diagnostics.
On macOS and Linux, measured repetitions also record `peak_rss_bytes`, the
profiled child's peak resident set size; the aggregate field is the largest
measured repetition. A timed-out child may terminate before the operating-system
resource wrapper can write this optional value.
Include-expanded programs are mapped
back to the file and line where each location originated; compiler_line
preserves the flattened line for diagnostics, and source_mapping records
whether that mapping succeeded. A nonzero target exit status is reported and
returned by the profiler. Target stdout and stderr are captured as separate
artifacts in the profile workspace. JSON reports also include call_edges with observed and completed
caller-to-callee calls. A panic or timeout report also includes the last 256
trace events in execution order, when the collector received the terminating signal,
plus `active_stack` with the tracked function names and any untracked overflow
depth at termination.
Pass `--recent-path` to include the same recent-event ring in every measured
run record, as well as the most recent path at the report top level, for
execution-path diagnostics.
Pass `--event-trace` to stream every trace event into each measured JSON run
record. This is intentionally opt-in because a hot loop can produce a large
trace. Full traces have a one-million-event safety budget by default; use
`--max-event-trace-events 0` only when an unbounded trace is intentional. Each
run reports captured and omitted trace records plus `trace_complete`, so a
truncated trace cannot be mistaken for a complete execution. The default
recent path remains capped at 256 events.
Distinct locations, call edges, and folded call paths are also bounded by the
collector. Their defaults are 32,768, 16,384, and 32,768 records respectively;
set `ELISA_PROFILE_MAX_LOCATIONS`, `ELISA_PROFILE_MAX_CALL_EDGES`, or
`ELISA_PROFILE_MAX_STACKS` to change them, with `0` meaning unlimited. Reports
preserve the configured limits, a `detail_budget_exceeded` quality flag, and
the number of dropped edge/path records so consumers can distinguish a sparse
profile from an intentionally bounded one.
The collector also enforces a shared 64 MiB per-run capture-byte budget by
default. Use `--max-capture-bytes N` (`0` means unlimited) to choose a different
budget. Reports expose `capture_byte_limit`, `capture_bytes_used`, and
`capture_bytes_dropped`; refused detail is reported with the
`capture_byte_budget` quality reason while aggregate event counts remain
available.

Useful controls:

    --format text|json|folded|html|speedscope  choose the profile report format (default: text)
    --mode full|functions|statements|values|diagnostic  choose event detail (default: full)
    -O0|-O1|-O2|-O3        choose the compiler optimization level (default: -O0)
    --warmup N             execute N unreported startup runs (default: 0)
    --repeat N             execute and merge N measured runs (default: 1)
    --progress PATH        atomically publish machine-readable stage status
    --path-map FROM=TO     remap one source-path prefix in report display fields
    --timeout SECONDS      terminate a runaway execution and retain its partial report
    --recent-path          include the last 256 trace events in each measured run
    --event-trace          include every trace event in each measured JSON run
    --max-event-trace-events N  cap full-trace records per run (0 means unlimited)
    --max-capture-bytes N  shared collector byte budget (0 means unlimited; default: 67108864)
    ELISA_PROFILE_MAX_LOCATIONS=N  cap distinct source-location records (0 means unlimited)
    ELISA_PROFILE_MAX_CALL_EDGES=N  cap distinct caller-to-callee records (0 means unlimited)
    ELISA_PROFILE_MAX_STACKS=N  cap distinct folded call-path records (0 means unlimited)
    --cwd PATH             run the target from PATH
    --stdin PATH           provide PATH as target standard input
    --env KEY=VALUE        set a target environment variable (repeatable)
    -- TARGET_ARG...       forward target arguments without shell re-parsing

The runtime collector uses the backend's complete-run trace callbacks, rather
than the runtime's bounded crash-debug ring, so loop counts are not truncated to
the last 256 events. Targets may use either the legacy `main() -> i64` entry or
the argv-aware `main(argc: i64, argv: mutable void&) -> i64` form. Repeated runs stop after the first nonzero target status and the
report retains every completed repetition, including min/mean/median/max,
sample standard deviation, and a labeled 95% confidence interval for measured
execution time. With fewer than two observations the interval is unavailable.
Locations receive
attributed wall-clock time from the native collector when trace timestamps are
available, together with their largest observed gap to the next trace event;
function summaries aggregate the same measurements and add inclusive/self
timing plus completed-call counts.
Text and HTML reports also list every measured repetition with its status, wall
time, CPU time, and peak RSS when available.
The summary also records the maximum call-stack depth tracked by the collector
and the number of entries beyond its 1024-frame capacity; a nonzero
`stack_overflow_entries` value means folded paths are necessarily incomplete.
Function call-events count observed entries, while completed-call counts include
only functions whose return hook was observed; panic and timeout reports can
therefore contain incomplete calls. Timing is an instrumented diagnostic
estimate: it includes collector overhead and is not statistical CPU sampling.
Wall timing includes sleeps and waits.
Collector records are sent over a dedicated inherited file descriptor during
normal profiler runs, so target stderr—including lines that resemble the
`ELISA_PROFILE` protocol prefix—remains available as program diagnostics and
cannot corrupt the profile. Native collector streams use record framing with
strict sequence numbers, byte lengths, and FNV-1a-64 checksums, followed by
begin/end markers; successful runs require a complete marker pair, while
timeout and signal captures retain explicit partial-capture state. Framed
transport loss is reported separately from aggregate event loss.
The folded format is compatible with flamegraph tooling: timing runs use
function self nanoseconds as weights, while count-only runs use observed call
entries as weights.
The `speedscope` format emits a self-contained sampled-profile JSON document
using the same stack weights, ready to open in Speedscope or another compatible
viewer.
The `report` command renders an existing JSON report offline, so changing
format or display limits never reruns the compiler or target. Pass
`--source PATH` when the report is being inspected from a checkout: the
profiler hashes that file and refuses to render if it does not match the
report's recorded workload identity. This prevents source locations from
being silently misattributed after a checkout changes.
The `recover` command reads a progress manifest and its still-present framed
capture, validates the source identity, ignores an incomplete tail, and emits
a clearly marked `quality.capture = recovered` report without claiming missing
termination or timing data.
The `doctor` command performs a read-only prerequisite check for the compiler
worktree, branch coverage, stage1 freshness, LLVM tools, runtime ABI, and the
content-validated runtime manifest. `doctor --json` is suitable for scripts.
The HTML format is a self-contained local report with summary cards, searchable
hotspots, an interactive folded-timing flame graph with zoom/reset, sortable
tables, source snippets, call graph, folded stacks, and recent execution path;
it has no network or runtime dependencies. The flame graph uses BigInt parsing
for serialized weights and treats frame labels as text, so large values and
hostile names do not become JavaScript code or rounded metrics.
The overview also shows workload reproducibility evidence: working directory,
stdin path and hash when available, forwarded target arguments, environment
override names without their values, and the explicit random-seed/input-hash
policy. Offline HTML preserves the same workload object as escaped detail.
The `compare` command accepts two JSON reports and emits a machine-readable or
text comparison of execution/compile timing, nullable CPU/RSS metrics, event
and location counts, thread counts, trace-quality counters, and per-function
count/timing deltas, caller→callee edge changes, folded stack-path changes,
and source-location changes keyed by source, kind, function, line, variable,
and signedness.
Added or removed records retain `null` on the missing side instead of being
rendered as zero:

    bin/elisa-profiler compare baseline.json candidate.json \
        --format json --output comparison.json

Comparison JSON output follows
[`docs/profile-comparison.schema.json`](docs/profile-comparison.schema.json).
Comparisons warn when source, workload metadata, collection mode, compiler
commit, optimization level, target exit status, or evidence quality differs.
Comparison gates support relative and absolute wall, CPU, RSS, and shared
function self-time budgets; requested gates return stable regression or
inconclusive exit statuses and serialize their policy and violations. Compiler-
stable cross-build identity matching remains a planned extension; current
comparisons report explicit keyed location changes without pretending that
readable names are stable identities.
Panics and timed-out children retain their partial trace when the process
reaches the collector's exit/signal handler. Timed-out targets run in an
isolated process group; the profiler terminates that group so forked target
children do not survive the profiling command.
