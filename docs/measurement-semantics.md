# Elisa profiler measurement semantics

This note defines the meanings of the version-1 native report fields. The
report is an instrumented event capture, not a statistical CPU sample. A
renderer must preserve that distinction in labels and comparisons.

The optional `workload` object identifies the inputs that make a capture
reproducible: source size, launch directory, stdin path when used, environment
override names, and the exact target argument vector. It is descriptive
provenance, not a claim that paths or stdin contents remain available after a
capture is moved; a missing content digest is represented as `null`.

## Units and clocks

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
- `timeout_s` is the requested positive per-execution wall-time limit, or `null`
  when no limit was requested. When the limit is reached, the native launcher
  sends `SIGTERM` to the target's process group, waits up to its bounded grace
  period, and then sends `SIGKILL` if necessary. A timed-out repetition keeps
  `timed_out: true`, reports the observed termination signal, and adds `timeout`
  to `quality.reasons`.
- `compile_ms` covers target compilation, object preparation, collector build,
  and link steps performed for the capture.
- `thread_count` is the maximum number of registered collector threads seen in
  the capture. It is not the operating system's final thread count.

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
- Tail-call elimination and inlining are compiler transformations. The
  instrumentation report only claims what the emitted callbacks observe; it
  does not infer removed frames.

## Completeness and failure states

The top-level `quality` object is orthogonal to the target's exit code:

- `quality.capture = complete` means the launcher waited successfully and the
  target exited normally with code zero.
- `target_exit` means a normal non-zero target exit was observed.
- `target_signal` means `waitpid` reported signal termination. `run.signal` is
  the signal number, including when the wait status also contains a core-dump
  flag.
- `profiler_failure` means the launcher could not wait or otherwise could not
  establish a valid child result.
- `quality.detail = degraded` means bounded detail was lost or stack recovery
  was incomplete. `quality.event_counts = partial` is reserved for dropped
  location records; dropped edges/stacks and omitted event-trace records are
  separately named reasons.

The `reasons` array is additive. A report can therefore say that the target
failed and that its detail budget was exceeded without pretending either fact
explains the other. An empty array is the only complete-quality case.

An empty or malformed collector capture is a profiler failure, even when the
target's own exit code would otherwise be zero. The one bounded exception is a
launcher timeout: if termination wins before the collector can flush, the
native launcher emits an empty but valid partial report with per-metric
completeness marked accordingly. A target that calls `_exit` without allowing
the collector to flush is still reported as missing evidence rather than as a
successful profile.

## Repetitions

Warmups are excluded from measured repetitions and are reported separately.
Measured repetitions are retained individually in `run.repetitions`. The
aggregate uses successful repetitions when at least one succeeds; otherwise it
uses all completed repetitions and labels `measurement_basis` accordingly.
No individual trace event is treated as an independent statistical sample.
The median is the middle value (the arithmetic mean of the two middle values
for an even count), and standard deviation is the population standard
deviation of the selected repetition durations after conversion to
microsecond precision. The report does not claim a confidence interval.

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

The current version-1 JSON writer emits integer values directly. Consumers
that must preserve values beyond JavaScript's exact integer range should parse
the raw JSON with an integer-capable decoder; the planned version-2 artifact
will add an explicit large-integer representation before those values are
exposed to a browser viewer.
