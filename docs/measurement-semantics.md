# Elisa profiler measurement semantics

This note defines the meanings of the version-1 native report fields. The
report is an instrumented event capture, not a statistical CPU sample. A
renderer must preserve that distinction in labels and comparisons.

The optional `workload` object identifies the inputs that make a capture
reproducible: source size, launch directory, stdin path when used, environment
override names, exact target argument vector, and native SHA-256 content
digests for readable source/stdin bytes. It is descriptive provenance, not a
claim that paths or stdin contents remain available after a capture is moved;
an unreadable optional input digest is represented as `null`.
`workload.reproducibility` makes the policy explicit: input bytes are hashed,
environment values are redacted, and `random_seed` is `null` with source
`not_controlled` until a target/runtime seed is deliberately supplied through a
documented control. Consumers must not infer deterministic execution from the
presence of hashes alone.

The optional top-level `host` object records the observation context captured by
the native launcher. `os` and `architecture` come from `uname`; the
`load_average_1m` value is the host's one-minute load average sampled before
compilation and is formatted to three decimal places. `load_average_source`
identifies the host API used. Affinity is explicitly reported as inherited and
unchanged because this profiler does not silently alter machine-wide CPU
settings. Power and thermal telemetry is currently `null` when no portable host
API is available; absence is intentional and must not be interpreted as a
measurement of a cool or unconstrained machine.

## Collection modes

`run.collection_mode` records the event policy used for the capture:

- `full` retains function, statement, and scalar-value records.
- `functions` retains function records and their caller/callee and folded-path
  context, without statement or scalar-value records.
- `statements` retains statement and function records, without scalar values.
- `values` retains scalar-value and function records, without statement records.
- `diagnostic` retains full instrumentation and enables the bounded event trace.

These are instrumented event modes, not statistical sampling modes. A sampling
request is rejected instead of being mislabeled as an instrumented capture.
The mode is a report identity field and must be considered when comparing
captures or interpreting missing event classes.

Every report also carries an explicit capability matrix. In the current build,
`sampling_detail`, `allocation`, and `tasks` are marked unsupported with stable
reasons because the compiler/runtime exposes instrumentation callbacks but no
native sampler, allocator-lifecycle stream, or task scheduler lifecycle stream.
`identity` is `compiler_stable_ids` when compiler-issued function and location
identity callbacks are observed, and `source_name_fallback` for legacy
compiler/collector streams. Stable-ID captures also declare the
`elisa.compiler.trace` namespace and identity-contract version `1`; fallback
captures use null namespace/version. These fields are declarations of evidence
coverage, not estimates.

Native collector streams begin with a capture marker and finish with a
completion marker. Successful target runs require both markers; timeout and
signal captures may intentionally be partial and expose
`summary.capture_complete: false`.

Native JSON captures also expose `run.capabilities`. Its event-class list is
the authoritative retained detail set; `trace`, `recent_path`, `timing`, and
`sampling` describe the active policies; and `detail_limits` records the
collector's configured location, edge, stack, and byte limits. A zero limit
means unlimited, matching the collector configuration.
Progress manifests additionally expose a `capture_index` for the framed
transport. `valid_bytes` is the end of the last checksum-validated frame,
`valid_frames` is its strict frame count, and `bytes` is the observed capture
file size at the last manifest update. A partial file may extend past
`valid_bytes`; recovery must never parse beyond the validated boundary.

Native readers also apply fixed safety limits before normalizing records: each
protocol line and framed payload is at most 1 MiB, a capture contains at most
one million validated frames, each detail array contains at most one million
records, and thread-loss/event detail has its own one-million-record bound.
These are parser safety limits, not measurement limits advertised to a target;
the collector's configured detail and byte budgets remain the authoritative
quality controls for a valid capture. A complete capture that exceeds a reader
limit is rejected as malformed, while recovery may stop at a final truncated
tail after the last validated frame.

`run.outcome` is the stable machine-readable termination classification. It is
`success` for a complete zero-exit target, `target_exit` for a non-zero target
exit, `target_signal` for an observed signal, `timeout` for deadline
termination, `profiler_failure` for launcher/wait failure, and
`incomplete_artifact` for a report reconstructed by `recover`. The
`incomplete_capture` value is reserved for a structurally incomplete capture
that can still be serialized; normal live capture rejects that condition before
emitting a report. The observed numeric exit/signal fields remain alongside the
classification.

The native text and HTML renderers preserve this distinction when a JSON report
is regenerated offline: they show the outcome and whether capture completeness
is `complete`, `partial`, or not recorded by an older report. HTML also exposes
the source SHA-256 and host provenance so a visual report does not hide the
identity or limitations of its evidence.

## Units and clocks

Every native report includes a `capture` contract describing the observation
scope. The process is one profiled child from launch through the launcher's
wait; thread identities are local to that capture and the thread count is the
maximum number of registered collector threads observed. Repetitions live in
`run.repetitions` and exclude warmups. Logical tasks are explicitly marked
`not_recorded` until the runtime exposes task lifecycle events. The current
instrumented timing clock is `CLOCK_MONOTONIC` wall time in integer
nanoseconds; `run.timing_clock` and the capability vector remain authoritative
for future clock domains.

Integer metrics are emitted as exact decimal JSON integer text. The bundled
HTML viewer extracts metric lexemes from the embedded report and converts them
to JavaScript `BigInt`; it does not use `JSON.parse` for timing, count, or
Speedscope weight fields. Consumers that use ordinary JavaScript JSON parsing
must apply the same arbitrary-precision policy or they may round values above
`2^53 - 1`.

- `events`, `locations`, `statement_events`, `value_events`, and
  `function_events` are callback observations. They count collector records,
  not function invocations unless the field is explicitly named
  `completed_calls`.
- `*_ns` fields are integer nanoseconds. With `location_timing: true`, they
  use the selected monotonic wall clock for the process. With CPU timing
  enabled by the collector build, the report must identify the clock as
  `cpu`; the two domains must not be compared as elapsed wall time.
- `execution_ms` is the launcher-observed elapsed duration around the child
  process. It includes startup and shutdown work and is not interchangeable
  with the sum of instrumented function durations.
- `execution_ms_mean`, `execution_ms_median`, `execution_ms_stdev`, and the
  `execution_ms_ci95_low`/`execution_ms_ci95_high` fields summarize the
  selected measured repetitions. The standard deviation is the sample standard
  deviation in microsecond precision (`n - 1` denominator). When at least two
  repetitions are available, the interval is a two-sided normal approximation
  using `1.96 * s / sqrt(n)`; fixed-point native arithmetic rounds its bounds
  conservatively outward. With fewer than two observations,
  `execution_ci95_available` is `false` and the equal bounds are descriptive,
  not an uncertainty interval. This is repetition-level benchmark evidence,
  never a claim that individual trace events are independent samples.
- `timeout_s` is the requested positive per-execution wall-time limit, or `null`
  when no limit was requested. When the limit is reached, the native launcher
  sends `SIGTERM` to the target's process group, waits up to its bounded grace
  period, and then sends `SIGKILL` if necessary. A timed-out repetition keeps
  `timed_out: true`, reports the observed termination signal, and adds `timeout`
  to `quality.reasons`.
- `compile_ms` covers target compilation, object preparation, collector build,
  and link steps performed for the capture.
- `cpu_user_ms` and `cpu_system_ms` are child-process CPU durations returned by
  the native `wait4` resource record, and `cpu_ms` is their sum. They are
  summed across the selected measurement repetitions, not compared with wall
  time; a missing host resource record leaves these fields `null`.
- `peak_rss_bytes` is the largest profiled-child resident-set value across the
  selected measurement repetitions. The native launcher reports the host
  `wait4` value in bytes; unavailable host accounting remains `null`.
- Comparison reports preserve `cpu_ms` and `peak_rss_bytes` as nullable
  metrics. Deltas are emitted only when both captures have resource records;
  a mismatch in availability is a warning, not a zero-valued measurement.
- `thread_count` is the maximum number of registered collector threads seen in
  the capture. It is not the operating system's final thread count.

Compiler-issued identity IDs are unsigned decimal `u64` values. A generic
function specialization includes its deterministic compiler symbol suffix in
the identity, so concrete instantiations with the same readable name and
source line remain separate records. Readable names are presentation labels;
they are never sufficient to merge stable-identity records.

## Comparison gates

The comparison command always emits optional `thresholds` and `gate` objects.
With no threshold option, `gate.status` is `not_requested` and the command
retains its normal zero exit status (or a validation error). Thresholds are
explicit policy, not a claim that every observed difference is statistically
significant.

Supported policies are:

- `--max-wall-regression-percent N` and `--max-wall-ms N` constrain the
  candidate's measured wall-time mean.
- `--max-cpu-regression-percent N` and `--max-cpu-ms N` constrain summed child
  CPU time when both captures have resource metrics.
- `--max-rss-regression-percent N` and `--max-rss-bytes N` constrain peak RSS
  when both captures have resource metrics.
- `--max-function-self-regression-percent N` applies the relative limit to
  every function present on both sides and reports one violation if any shared
  function exceeds it.

Percent values are whole percentages from `0` through `1,000,000`; zero means
no increase is permitted. Absolute wall/CPU values are integer milliseconds,
and RSS values are integer bytes. A zero baseline treats any positive candidate
as a relative regression. A requested gate becomes `inconclusive` rather than
failing when source, workload, mode, compiler, optimization, target outcome,
or bounded-evidence identity is not comparable, or when a required resource or
shared-function metric is unavailable. Gate exit status `5` means regression,
`4` means inconclusive, and `0` means the requested policy passed. The JSON
`gate.violations` array contains stable policy names suitable for CI logs.

## Function and stack accounting

- `call_events` is incremented when a function entry is observed.
- `completed_calls` is incremented only when a matching function exit is
  observed. A crash, process termination, stack mismatch, or overflow can make
  it smaller than `call_events`.
- `inclusive_ns` includes observed child time. `self_ns` is the portion of an
  observed interval not attributed to a completed child. An incomplete frame
  never contributes a fabricated completion interval.
- Recursive calls are separate stack nodes when their parent path differs, but
  function summaries intentionally aggregate the readable function key.
  Readable names are not stable cross-build identities; source and compiler
  identity metadata must be used before comparing same-named functions.
- A crash or externally delivered termination signal may interrupt active
  calls before their exit callbacks run. The signal-safe collector preserves a
  bounded `active_stack` snapshot with tracked and overflow depths; it is
  diagnostic evidence of the interrupted path, not completed-call evidence.
  Reports containing this snapshot are always marked with degraded detail and
  partial function/call-edge/stack/timing completeness.
- Tail-call elimination and inlining are compiler transformations. The
  instrumentation report only claims what the emitted callbacks observe; it
  does not infer removed frames.
- Native offline readers reject normalized detail records whose accounting is
  impossible: completed calls cannot exceed observed calls, self time cannot
  exceed inclusive time, and a maximum interval cannot exceed its aggregate
  interval. These checks protect every renderer and comparison from accepting
  a syntactically valid but semantically corrupt capture.
- Function records expose an optional compiler-issued `identity_id`; legacy
  captures omit it. A function present on only one side has `null` metrics on
  the missing side; the comparison never treats absence as a measured zero.
- Caller→callee records expose optional `caller_id` and `callee_id`, stack
  records expose optional semicolon-delimited `stack_ids`, and source/event
  location records expose optional `identity_id`. Readable names and source
  metadata remain in every record for diagnostics and legacy compatibility.
- Offline comparison uses those IDs for function, edge, stack, and source-location
  matching whenever the compared records provide them. It does not merge a
  stable-ID record with a legacy readable-name record, and it reports a
  stable-identity coverage mismatch as a warning/inconclusive requested gate.
  IDs are retained as decimal text at the Elisa parser boundary so values above
  signed 64-bit range remain exact. It also validates the declared stable-ID
  namespace/version and treats an unknown or mismatched contract as the same
  warning/inconclusive condition.

## Completeness and failure states

The top-level `quality` object is orthogonal to the target's exit code:

- `quality.capture = complete` means the launcher waited successfully and the
  target exited normally with code zero.
- `target_exit` means a normal non-zero target exit was observed.
- `timeout` means the launcher reached the requested deadline and terminated
  the target. `run.signal` still records the termination signal, and the
  timeout reason remains additive.
- `target_signal` means `waitpid` reported signal termination. `run.signal` is
  the signal number, including when the wait status also contains a core-dump
  flag.
- `profiler_failure` means the launcher could not wait or otherwise could not
  establish a valid child result.
- `quality.detail = degraded` means bounded detail was lost or stack recovery
  was incomplete, including a signal/timeout capture that may have interrupted
  active callbacks. `quality.event_counts = partial` is reserved for dropped
  location records; dropped edges/stacks and omitted event-trace records are
  separately named reasons. An `active_stack` snapshot identifies the last
  observed call path without upgrading any completion count.

The `reasons` array is additive. A report can therefore say that the target
failed and that its detail budget was exceeded without pretending either fact
explains the other. An empty array is the only complete-quality case.

An empty or malformed collector capture is a profiler failure, even when the
target's own exit code would otherwise be zero. The one bounded exception is a
launcher timeout: if termination wins before the collector can flush, the
native launcher emits an empty but valid partial report with
`quality.capture = timeout` and per-metric completeness marked accordingly. A
target that calls `_exit` without allowing
the collector to flush is still reported as missing evidence rather than as a
successful profile.

## Repetitions

Warmups are excluded from measured repetitions and are reported separately.
Measured repetitions are retained individually in `run.repetitions`. The
aggregate uses successful repetitions when at least one succeeds; otherwise it
uses all completed repetitions and labels `measurement_basis` accordingly.
Each repetition also reports `detail_records` for normalized locations,
functions, caller-to-callee edges, and stack paths. These are evidence counts
for that run, not independent statistical samples; a lower count must be
interpreted with the repetition's drop, overflow, and completeness fields.
The `completeness` object makes that interpretation explicit for events,
locations, functions, call edges, stacks, timings, and resource metrics. Its
values are `exact`, `partial`, or `unavailable`; `unavailable` is reserved for
metrics the host did not provide, while `partial` means the capture cannot
support an exact claim.
When native collection is enabled, `thread_loss` records the event count and
loss counters for each profiler thread. `repetition` identifies the target
run because collector thread IDs are local to a capture. `location_dropped`,
`call_edge_dropped`, and `stack_dropped` identify bounded-detail loss;
`trace_dropped` and `bytes_dropped` identify omitted event-trace records.
`event_start` and `event_end` bracket the first and last observed event
sequence for that thread, so loss is localized to an evidence interval without
claiming exact drop timestamps. They are nullable for legacy captures. A
thread record is diagnostic evidence, not a replacement for aggregate counters.
No individual trace event is treated as an independent statistical sample.
The median is the middle value (the arithmetic mean of the two middle values
for an even count), and standard deviation is the sample standard deviation of
the selected repetition durations after conversion to microsecond precision.
For at least two observations, the report also emits a two-sided normal
approximation using `1.96 * s / sqrt(n)`. With fewer than two observations,
`execution_ci95_available` is false and equal descriptive bounds are emitted;
they must not be presented as uncertainty.

## Loss and unsupported values

Configured zero limits mean unlimited for the current collector. Non-zero
limits bound distinct location, call-edge, and call-path detail. When a limit
or allocation failure drops detail, the corresponding counter is incremented
and the quality reason is retained. A zero value in a metric is not a synonym
for missing data; unsupported metrics remain `null` in the schema.

`capture_byte_limit` is the shared per-run collector budget. It covers the
collector's aggregate tables, registered thread state, call-path nodes, and
estimated retained event-trace records. `capture_bytes_used` is the currently
reserved collector detail budget at flush time; `capture_bytes_dropped` is the
saturated sum of detail reservations refused by that budget. A zero byte limit
means unlimited. Aggregate event counts remain exact when only detail
reservations are refused, while `quality.detail` becomes `degraded` and the
`capture_byte_budget` reason is emitted. Repetition summaries report the
per-run values; the aggregate summary sums used/dropped bytes across measured
runs and retains the last configured limit.

Target stdout and stderr are separate from the collector transport. The native
launcher spools each stream independently, reports the captured text as
`program_stdout`/`program_stderr` when non-empty, and emits matching boolean
`program_stdout_truncated`/`program_stderr_truncated` fields. Each aggregate
stream is capped at the named native program-output limit; a true flag means
the diagnostic text is incomplete and must not be treated as the complete
target transcript.

The current version-1 JSON writer emits integer values directly. Consumers
that must preserve values beyond JavaScript's exact integer range should parse
the raw JSON with an integer-capable decoder; the planned version-2 artifact
will add an explicit large-integer representation before those values are
exposed to a browser viewer.
