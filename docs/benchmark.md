# Native benchmark manifests

Optimization priority: maximize throughput, not minimize memory. Report peak
memory as a tradeoff and check for pressure or instability, but higher RSS alone
does not disqualify a measured throughput improvement. Instruction counts are
supporting evidence, not a substitute for elapsed-time measurements.

`benchmark` is the reproducible baseline/candidate workflow. The manifest is
parsed by the Elisa-native executable; it never invokes a shell or the legacy
Python profiler. The command builds and captures the baseline and candidate
with identical workload controls, then sends the two JSON captures through the
native comparison engine.

```sh
bin/elisa-profiler benchmark examples/benchmark_pipeline.json \
  --format json --output build/pipeline-comparison.json
```

The manifest's `baseline_source` and `candidate_source` are source paths
resolved by the current working directory. `target_arguments`, `stdin`,
`working_directory`, and `environment` are forwarded through the same direct
exec boundary as `profile`. `random_seed` becomes the explicit
`ELISA_RANDOM_SEED` control in both sides, and `embed_source` makes the
intermediate captures independently navigable before they are cleaned up.

`repetitions` and `warmups` are passed unchanged to both captures. The two
captures are executed in `baseline_first` order by default. Set
`execution_order` to `candidate_first` to reverse that order, or to
`randomized` to choose a deterministic order from the baseline/candidate
source identities and optional `random_seed`. The comparison output records
the actual order as `execution_order`, including whether a randomized choice
selected the baseline or candidate first. These are paired executions with a
shared workload definition; they do not claim to eliminate scheduler noise.
True within-repetition alternation remains a future optimization of the
runner, while exact native comparison and machine-readable gate outcomes are
already available.

## Compiler instrumentation performance checkpoint

On 2026-09-08, compiler change `844e2abc` added `-ftrace-functions`, and
profiler change `eb3ab40` selected it for source-built function profiles.
An alternating three-pair local measurement compiled
`examples/collection_growth_workload.elisa` with two instrumented copies of
the same self-host compiler source. Both used the same timed collector,
runtime object, optimization level (`-O0`), and linker flags. Capture output
went to `/dev/null` for this callback-overhead comparison.

| Instrumentation | Wall seconds, three runs | Median |
| --- | --- | --- |
| Full trace, function collection mode | 4.52, 3.95, 3.83 | 3.95s |
| Function-only trace, function collection mode | 3.85, 3.15, 3.32 | 3.32s |

The median reduction was approximately 16%. Instrumented compiler object
size fell from 31,387,792 to 22,533,648 bytes (approximately 28%). Compiled
workload objects were byte-identical across all pairs. Separate captures
using identical arguments, including the output pathname, matched call and
completion counts for all 3,101 function records. Pathnames must match for
count comparisons: compiler string processing and allocation counts depend
on them.

A normal CLI capture with the function-only prebuilt compiler completed its
target in 3.44s; that is target execution time, not total CLI latency.
Function and call-edge detail was complete, but stack paths reached the
32,768-path limit and were explicitly marked partial. These local timings
are a performance checkpoint, not a portable speed guarantee or evidence
that profiling overhead has been eliminated.

Profiler change `8826074` subsequently reused SHA-256 schedule storage across
message blocks. Two reverse-order end-to-end comparisons using the same
function-only prebuilt compiler and identical arguments measured old/new CLI
wall times of 15.94/8.91s and 15.57/8.06s (approximately 44–48% lower). Peak
resident memory fell from 691–704 MB to 593–594 MB. These runs include
provenance hashing, target execution, decoding, and report writing, unlike
the callback-only measurements above. Concurrent self-host validation was
running, so these remain local checkpoints rather than isolated release
benchmarks. Empty, short, padding-boundary, and million-byte SHA-256 vectors
pass the Elisa-native `make hash-smoke` gate; the full native regression
suite also passed with the rebuilt profiler.

An `-O1` profiler build at revision `c969164` passed the full native regression,
including cross-section capture-completeness checks that fail at `-O2`.
Three alternating end-to-end pairs measured `-O0`/`-O1` wall times of
9.72/9.28s, 10.77/11.69s, and 12.20/12.78s. This showed no consistent benefit;
the installed profiler remains at `-O0`. Optimization-level changes alone
are not counted as performance gains.

Change `c456375` removes the full-input padding copy in SHA-256. Complete
blocks are read directly from the input; only the final partial block and
padding use temporary storage (at most two blocks). Known-vector and
input-preservation tests pass, as does the full native regression suite.
Three alternating old/new CLI pairs measured 11.93/12.97s, 10.09/8.97s, and
10.64/8.87s: median 10.64s versus 8.97s, with one slower pair. Peak resident
memory decreased from 593–599 MB to 532–553 MB. These comparisons used the
same compiler revision before integrating the subsequent diagnostic fixes.

Sampling was then compared using the same compiler object revision and workload
with three callback configurations. Three-run wall-time medians were 3.32s
for full tracing, 2.19s for function-only tracing, and 2.02s for function-only
tracing with thread registration locking only when registration is needed.
Corresponding user-CPU medians were 3.13s, 2.06s, and 1.87s. Sampling source
builds now select function-only instrumentation. The approximately 39% wall
reduction is against the previous sampling configuration, not against an
uninstrumented compiler. Capture output went to `/dev/null` in this comparison;
the end-to-end sampling suite separately validates retained samples and exports.

A subsequent raw compiler sampling capture retained 1,608 samples. Every frame's
payload length, FNV-1a checksum, and sample sequence validated; the collector
reported zero missed samples and no sampled stack overflow. Common leaf frames
included `note_local_type`, `arena_realloc`, `check_full_into`, and effect checks.
This validates practical capture quality, not an unbiased attribution of all
compiler CPU time: only instrumented Elisa stacks are represented, and callback
overhead remains. A same-revision uninstrumented comparison is required before
claiming an absolute sampling-overhead factor.

The subsequent same-source, same-generation comparison at compiler `bd25a22a`
used the self-host generation-2 executable as baseline and a function-traced
compiler built by that same seed. Three alternating baseline/sample wall times
were 1.60/2.04s, 1.59/1.73s, and 1.45/1.72s; median overhead was approximately
9%. User CPU medians were 1.49s and 1.68s (approximately 13% overhead).
Workload output objects matched byte-for-byte in every pair. These timings
exclude report transport and CLI preparation, with sampling sent to `/dev/null`.
A separate normal CLI run completed successfully with 1,031 retained samples,
zero reported misses, and complete capture/detail quality. Comparisons against
the stage-0-built seed are not an instrumentation-overhead baseline: that is a
different compiler generation with different generated code.

### Full self-build sampling checkpoint

With compiler `bd25a22a`, a sequential full self-build pair used the same
generation, source, `-O0`, output pathname, and target arguments. Baseline wall
time was 307.99s and user CPU 288.81s. At a 5,000 µs sampling period, target
wall time was 391.175s and user CPU 355.258s: approximately 27% wall and 23%
user-CPU overhead in this single pair. Total sampled CLI wall time was 396.71s,
about 5.5s beyond target execution. This is not a repeated-trial confidence
estimate, and the smaller workload's 9% result must not be generalized to it.

Both builds produced byte-identical 19,083,744-byte objects. The 19.4 MB JSON
report retained 58,399 samples, zero reported misses, and complete capture/detail
quality. Target peak RSS was 875,085,824 bytes sampled versus 1,027,948,544 bytes
baseline; do not infer a general memory improvement from one run. The capture
is useful at self-host scale, but reducing full-scale sampling overhead remains
an open performance task.

The checked-in example gates aggregate wall time only. It deliberately does not
gate every function's self time: very short functions can quantize to zero in
one capture and a microsecond in the other, which is useful evidence but makes
a whole-workload example intermittently fail on timer quantization rather than
on a meaningful regression. Use `max_function_self_regression_percent` for a
workload with a documented minimum per-function duration, and keep the
exploratory function rows for the remaining evidence.

Intermediate reports use `<output>.baseline.json` and
`<output>.candidate.json`. The native command refuses to reuse pre-existing
intermediate names and removes both reports and their progress manifests after
the comparison completes. A failed side is surfaced as a benchmark failure and
does not produce a misleading comparison.

## Sampling callback TLS layout

The collector groups its per-thread stack, depth, overflow state, and thread
registration pointer in one TLS allocation. This lets Darwin callbacks reuse
one resolved TLS base; state remains isolated per thread. The permanent
callback benchmark now includes stable-identity sampling entry/exit pairs.

On the development host, five repetitions of 10 million entry/exit pairs at a
5 ms sampling period (capture transport redirected to `/dev/null`) reduced
median elapsed callback-loop time from 170,355,000 to 114,825,000 ns, about 33%.
This includes loop overhead and is not a whole-compiler speedup claim. Three
small compiler workload pairs produced identical objects; their median user
CPU times were 2.15/2.10 seconds, with noisy wall times. Full-scale impact must
be measured separately. Native, sampling, mismatch/overflow, strict-build, and
sanitizer checks cover the new layout.

The first full self-build with unified TLS completed with a byte-identical
object, 69,489 retained samples, zero reported misses, and complete quality.
Target wall/user CPU were 516.983/435.735 seconds; total CLI wall was 524.49
seconds. This is worse than the earlier 391.175/355.258-second capture, despite
the callback-loop gain. Host CPU availability varied during this run. A fresh
old-layout control is required before attributing the difference to TLS; the
optimization is not yet a demonstrated full-build improvement.

The subsequent old-layout control completed at 542.671 seconds target wall /
401.819 seconds user CPU, with a byte-identical object, 67,849 retained samples,
zero reported misses, and complete quality. The user stopped other agents partway
through that control; observed load average fell substantially. Because host
conditions changed during the sequence, these runs do not isolate the layout's
effect. A fresh sequential unified/old-layout pair under the quieter conditions
is needed before deciding whether to retain the optimization.

That sequential pair completed with target wall/user CPU of 318.154/310.140
seconds for unified TLS and 319.366/312.107 seconds for the old layout. Both
objects matched the baseline; 46,499/46,457 samples were fully retained with
zero reported misses or stack overflow. Total CLI wall was 321.88/323.01 seconds.
This does not reproduce the earlier regression, but the difference is too small
for a meaningful whole-build speedup claim from one pair. The TLS layout is
retained for its measured callback-loop gain and passing correctness checks.

Despite the `quiet-` artifact names, four other CPU-heavy jobs were discovered
still running throughout this pair (three debugger compiler jobs and an `epq`
workload). None was stopped by the profiler agent. The pair is same-session
evidence under background load, not an isolated-machine benchmark. A fresh
uninstrumented control is still needed to quantify current capture overhead.

The fresh same-generation uninstrumented self-build then completed in 292.03
seconds wall / 287.57 seconds user CPU, with the same output object. Against
the nearby unified-TLS capture (318.154/310.140 seconds), this is approximately
8.9% target wall / 7.8% user CPU overhead. Treat this as one same-session
comparison under the documented background load, not a universal overhead
guarantee or evidence that the earlier differently loaded runs were comparable.

## Allocation ABI evidence fast path

Negotiation and event callbacks now read their monotonic ABI-evidence bits
before doing atomic fetch-or. Already-observed bits require no atomic write;
concurrent first observations still merge atomically. Negotiation results,
capture mode filtering, and event collection are unchanged. A synchronized
four-thread regression checks that all independent evidence bits survive
repeated concurrent updates, and native/sampling/sanitizer checks pass.

Seven repetitions of 10 million negotiation/event pairs in sampling mode
reduced median callback-loop cost from 2.578 to 1.817 ns per hook, about 30%.
The permanent callback benchmark includes this variant. Three small compiler
workload pairs produced identical objects but no clear speedup: median target
wall 1.41/1.47 seconds and user CPU 1.37/1.39 seconds before/after. This is a
hook-cost improvement, not a claimed full-compiler performance gain.

## Large Speedscope export validation

The 58,399-sample self-build capture exposed stack exhaustion in the previous
`-O0` profiler during Speedscope rendering. Reusing temporary storage alone,
extracting a helper alone, and changing optimization alone did not resolve it.
The profiler now builds at `-O1` and keeps temporary frame construction in a
non-inlined helper. Target compilation and compiler bootstrap settings are
unchanged. This is a scalability fix, not a claimed general wall-time speedup.

The full capture exports successfully with 679,751 frame occurrences. Every
expanded stack, sample weight, total weight, and sampling unit was checked
against the original capture. That check also exposed and fixed an existing
trailing-space error in leaf frame names. Native regression coverage includes
524,288 frame occurrences and verifies all expanded names and weights.
The subsequent private Elisa frame index deduplicates exact names in first-seen
order. On that same capture it reduces frame entries from 679,751 to 1,713 and
file size from 26,687,469 to 3,078,782 bytes (88.5% smaller). Expanded stacks,
weights, and profile metadata match the pre-index export exactly. Peak resident
memory in the first measured pair falls from 196,820,992 to 153,370,624 bytes
(22.1%). Regression coverage checks repeated names, deliberate hash collisions,
multiple table growths, and JSON-escaped names. These export measurements do not
change the target sampling-overhead measurements above.
Three subsequent sequential baseline/candidate pairs, without concurrent test
runs, have median wall times of 3.76/3.79 seconds and identical 3.63-second
median user CPU time. Thus the demonstrated gains are export size and memory,
not rendering speed; no speedup is claimed from this change.

## Compiler optimization guided by the profiler

Compiler commit `ffbb5865` narrows the abstract-effect expression walk's
annotation table to its exact dependencies, retaining order and duplicates.
Declaration and handler validation still use the complete table. The prior
46,499-sample compiler capture identified repeated effect declaration/template
scans as a hotspot; this change reduces those scans without disabling checks.

Two sequential full-compiler build pairs used identical current source, `-O0`,
and output paths, with the second pair reversing run order:

| Pair | Baseline wall/user seconds | Candidate wall/user seconds |
| --- | --- | --- |
| Baseline then candidate | 163.13 / 161.80 | 137.00 / 135.92 |
| Candidate then baseline | 165.00 / 163.27 | 136.52 / 135.45 |

This is about 16–17% less full-build time on this workload, not a claim for all
Elisa programs. Every output object was byte-identical. All 93 top-level effect
fixtures also matched baseline exit codes, diagnostics, and successful objects;
the existing effect-handler suite passed. Baseline was the validated `2f8b2180`
gen3 compiler; the candidate was built locally with the compact-table change.
Both timing variants were uninstrumented. Native sampling remains unfinished.

Local evidence: `build/effects-full-{baseline,candidate}.log`, the corresponding
`-reverse.log` files, `effects-parity-{baseline,candidate}` directories and
results logs, and `effects-candidate-smoke.log`. These build artifacts are
ignored; this section preserves the measured result and its scope.

Compiler commit `8ff99380` adds an early filter in the fallibility checker:
only `__try_without_else` rows with a known-call marker proceed to scope
resolution. Previously those lookups ran even for unrelated annotations.
Existing diagnostic guards are unchanged.

| Pair | Effects-optimized baseline wall/user seconds | Try-filter candidate wall/user seconds |
| --- | --- | --- |
| Baseline then candidate | 137.50 / 136.18 | 122.58 / 121.20 |
| Candidate then baseline | 135.71 / 134.99 | 121.31 / 120.57 |

This is another 10–11% reduction on the full-compiler workload relative to
`ffbb5865`, not an additive percentage claim. Each pair used the same current
source and output path; all four objects were byte-identical. Logs are
`build/try-full-{baseline,candidate}.log` and their `-reverse.log` counterparts.

The candidate exactly matched all 390 baseline diagnostic/try fixture results:
194 compiled, 176 exited 1, 19 exited 2, and one retained a pre-existing trap.
Successful LLVM IR and diagnostics matched byte-for-byte. Module-local
error-family parity also passed. These are equivalence checks, **not 390
passing fixtures**: at that checkpoint `try_void_else_void.elisa` trapped in LLVM
because a fallback path attempted `alloca void`; the pre-filter compiler also
reproduced it. Follow-up compiler commit `d378b4e7` fixes that separate defect,
with O0–O3 stage0 parity for no-op and conditional side-effect recovery on ordinary
and generic calls. This correctness fix is not part of the speedup measurement.

## Region-forwarding lookup filter (2026-09-08)

Compiler commit `a4f02f4a` avoids a whole callee-fact-table scan when the argument
root is not a caller parameter or its region fact is already true. Facts remain
monotone; owner resolution and propagation for unresolved parameters are unchanged.
A fresh full-build instrumented profile of `5e03c579` observed this lookup as the
largest leaf (1,268 of 20,051 samples). This is sampled instrumented-stack
attribution, not exact native self-time.

Two sequential full O0 compiler-build pairs, with order reversed in the second,
measured baseline/candidate wall times of 121.75/116.38 and 122.15/116.88 seconds.
User CPU times were 120.86/115.43 and 121.20/115.93 seconds. Both compilers were
self-hosted, compiled identical source to the same output path, and all four
objects matched byte-for-byte: approximately 4.3–4.4% less wall time on this host.
These are incremental comparisons against `5e03c579`, not an additive claim with
earlier speedups. Logs: `build/region-full-{baseline,candidate}.log` and their
`-reverse.log` counterparts.

All 42 selected region/arena/forwarding fixtures matched baseline exit status,
diagnostic bytes, and successful LLVM output; this includes existing refusals,
not 42 successful compilations. Caller-owned growth and forwarded nested-region
runtime probes returned the expected 142 and 42 with both compilers. A fresh
seed and full self-host gate passed for the committed revision: five regression
probes, full compiler emission, byte-identical gen3/gen4, and 40 matching repeat
emissions. The rebuilt profiler also passed native and sampling regressions.
Logs: `build/region-committed-self-host.log`, `build/region-native-regression.log`,
and `build/region-sampling-regression.log`.

## Segment-flow annotation filter (2026-09-08)

Compiler commit `b707efec` builds a compact segment-flow annotation table once
before walking function bodies. It retains all four transition/requirement
annotation kinds in their original order, including duplicates. Existing owner
resolution, branch merging, and diagnostics are unchanged.

Two full O0 compiler-build pairs measured baseline/candidate wall times of
115.59/103.12 and 115.69/103.06 seconds, reversing execution order in the second
pair. User CPU times were 114.92/102.38 and 114.97/102.30 seconds. All four emitted
objects were byte-identical. This is about 10.8–10.9% less wall time against the
region-optimized `a4f02f4a` baseline on this host, not an additive percentage
claim with prior optimizations. Both binaries were self-hosted and used identical
source/output paths. Logs: `build/segment-full-{baseline,candidate}.log` and their
`-reverse.log` counterparts.

All 385 diagnostic fixtures and two focused segment-flow fixtures matched
baseline exit statuses, diagnostic bytes, and successful LLVM output. These
include existing refusals, not 387 successful compilations. The focused cases
cover explicit host restoration, guest/host mismatches, and unknown ambient
ownership after a branch merge. A fresh seed and full self-host validation of
the committed revision passed: five initial probes, full compiler emission,
byte-identical gen3/gen4, and all 40 repeated emissions. The rebuilt profiler
also passed native and sampling regressions. Logs:
`build/segment-committed-self-host.log`, `build/segment-native-regression.log`,
and `build/segment-sampling-regression.log`.

## Aggregate-state call annotation filter (2026-09-08)

Compiler commit `37a988dd` restricts the aggregate-state call checker's repeated
arity lookups to `__aggregate_state` rows. It preserves order and duplicates:
each repeated row represents another state slot. The shared lookup helper and
standalone arity checker are unchanged.

Two full O0 compiler-build pairs measured baseline/candidate wall times of
103.05/96.74 and 102.60/96.78 seconds, reversing order in the second pair.
User CPU times were 102.34/96.11 and 102.02/96.14 seconds. All four objects
were byte-identical. This is 5.7–6.1% less wall time against `b707efec` on this
host, not an additive claim with previous gains. Both binaries were self-hosted
and compiled identical sources to the same output path. Logs:
`build/aggregate-full-{baseline,candidate}.log` and their `-reverse.log` variants.

All 385 diagnostic fixtures plus two new multi-slot fixtures matched baseline
exit statuses, diagnostics, and successful LLVM output; this includes existing
refusals. The accepted two-slot fixture also executed and returned 42, while
the rejected fixture retained the expected `[?, &]` versus actual `[?, ?]`
diagnostic. The committed revision passed fresh bootstrap validation: five
initial probes, full compiler emission, byte-identical gen3/gen4, and all 40
repeat emissions (`build/aggregate-committed-self-host.log`). The rebuilt profiler
also passed native and sampling regressions (`build/aggregate-native-regression.log`
and `build/aggregate-sampling-regression.log`).

## Lambda-argument scan filter (2026-09-08)

Compiler commit `27ffe9f3` avoids the lambda-return checker's declaration scan
for calls with no direct lambda arguments. Recursive argument traversal remains
unchanged, so an inner call's invalid lambda still produces its diagnostic.

Two full O0 build pairs measured baseline/candidate wall times of 96.38/92.66
and 96.43/92.69 seconds, with order reversed in the second pair. User CPU times
were 95.80/92.09 and 95.89/91.99 seconds. All four objects were byte-identical:
about 3.9% less wall time against `37a988dd` on this host. Both binaries were
self-hosted and used identical source/output paths. These are incremental
measurements, not an additive claim with earlier gains. Logs:
`build/lambda-full-{baseline,candidate}.log` and their `-reverse.log` variants.

All 385 diagnostic fixtures plus two nested-call fixtures matched baseline exit
status, diagnostic bytes, and successful LLVM output, including existing refusals.
The accepted nested-call fixture also returned 42 at runtime. Fresh bootstrap
validation of the committed revision passed: five initial probes, full compiler
emission, byte-identical gen3/gen4, and all 40 repeat emissions. Evidence:
`build/lambda-committed-self-host.log`. The rebuilt profiler passed native and
sampling regressions (`build/lambda-native-regression.log` and
`build/lambda-sampling-regression.log`).

## Derived-state parameter lookup filter (2026-09-08)

Compiler commit `f1796360` defers parameter-type lookup until the argument has
a tracked derived-state slot marked changed. Unchanged/untracked arguments
cannot produce this diagnostic. Postcondition lookups are unchanged.

Two full O0 build pairs measured baseline/candidate wall times of 92.61/86.98
and 92.50/87.02 seconds, reversing order in the second pair. User CPU times
were 91.92/86.37 and 91.96/86.41 seconds. All four objects were byte-identical:
5.9–6.1% less wall time against `27ffe9f3` on this host. Both binaries were
self-hosted and compiled identical source/output paths. This is an incremental
comparison, not an additive claim with prior gains. Logs:
`build/derived-full-{baseline,candidate}.log` and their `-reverse.log` variants.

All 387 selected diagnostic/derived/typestate fixture results matched baseline
exit statuses, diagnostics, and successful LLVM output, including existing
refusals. An additional focused fixture retained the changed `Alive` to `Dead`
argument-mismatch and restoration diagnostics exactly. Fresh bootstrap
validation of the committed revision passed: five initial probes, full compiler
emission, byte-identical gen3/gen4, and all 40 repeat emissions. Evidence:
`build/derived-committed-self-host.log`. The rebuilt profiler also passed native
and sampling regressions (`build/derived-native-regression.log` and
`build/derived-sampling-regression.log`).

## Unhandled-error annotation filter (2026-09-08)

Compiler commit `90462733` compacts the unhandled-error checker's annotations
to error-return markers, try-wrapper markers, and function-module provenance.
Order and duplicates remain intact; shared fallibility and propagation logic
is unchanged.

Two full O0 build pairs measured baseline/candidate wall times of 86.69/79.04
and 86.97/79.11 seconds, reversing order in the second pair. User CPU times
were 86.16/78.55 and 86.41/78.55 seconds. All four objects were byte-identical:
8.8–9.0% less wall time against `f1796360` on this host. Both binaries were
self-hosted and used identical source/output paths. This is an incremental
comparison, not an additive claim with previous gains. Logs:
`build/unhandled-full-{baseline,candidate}.log` and their `-reverse.log` variants.

All 397 diagnostic/try/unhandled/error-union fixture results matched baseline
exit statuses, diagnostics, and successful LLVM output, including existing
refusals. The module-scoped handled-call fixture also returned 42 at runtime.
Fresh bootstrap validation of the committed revision passed: five initial
probes, full compiler emission, byte-identical gen3/gen4, and all 40 repeat
emissions (`build/unhandled-committed-self-host.log`). The rebuilt profiler
also passed native and sampling regressions (`build/unhandled-native-regression.log`
and `build/unhandled-sampling-regression.log`).

## Combined compiler optimization result (2026-09-08)

An archived self-hosted `2f8b2180` compiler and the self-hosted `90462733`
compiler each compiled identical current compiler source at O0, using the same
runtime and output path. Two sequential pairs reversed execution order:

| Execution order | Baseline wall / user seconds | Current wall / user seconds |
| --- | --- | --- |
| Baseline, current | 162.64 / 161.56 | 79.05 / 78.49 |
| Current, baseline | 162.58 / 161.76 | 79.03 / 78.50 |

All four emitted objects were byte-identical. This measures approximately
2.06× compilation throughput, or 51.4% less wall time, on this full-compiler
workload and host. It is a direct combined comparison, not a sum of incremental
percentages, and does not establish speedups for other workloads or profiler
overhead. Logs: `build/combined-full-{baseline,current}.log` and their
`-reverse.log` variants. Baseline executable: `build/elisac-effects-baseline`;
current executable: the dedicated compiler's `build/self_host_gen2/elisac-stage1-gen2`.

## Eliminate duplicate effect-reference lookup (2026-09-08)

The fresh `90462733` instrumented capture completed with 12,843 samples, zero
reported missed samples or dropped frames, and an 85.499-second target run.
Its largest sampled leaf was `ae_effect_declared` (537 samples), called from
effect-reference validation. This is instrumented stack attribution, not native
self-time. Evidence: `build/post-unhandled-full-profile.json`.

Removing a redundant declaration lookup after an already-returning branch
preserved all 483 selected effects/permissions/diagnostic fixture exit statuses,
messages, and successful LLVM output, including existing refusals.
Full O0 baseline/candidate pairs measured 78.96/77.07 seconds and, with order
reversed, 79.05/77.06 seconds. User CPU times were 78.43/76.56 and 78.50/76.53.
All four emitted objects were byte-identical: approximately 2.4–2.5% less wall
time against `90462733` on identical current source. Both binaries were
self-hosted. Logs: `build/effect-ref-full-{baseline,candidate}.log` and their
`-reverse.log` variants. Fresh committed bootstrap validation passed on
`d4451281`: five initial probes, full compiler emission (19,107,488 bytes),
byte-identical gen3/gen4 objects, and identical objects across 40 repeat runs.
Evidence: `build/effect-ref-committed-self-host.log`. The rebuilt profiler also
passed native and sampling regression checks (`build/effect-ref-native-regression.log`
and `build/effect-ref-sampling-regression.log`). This is not a complete test-suite claim.

## Compact interprocedural frame annotations (2026-09-08)

The frame checker now constructs one ordered table of direct changes, frame-law
fields, and fulfillment rows, using private named constants. It retains duplicates
and inherited-law fields; unconstrained-callee diagnostics remain unchanged.
All 388 selected diagnostic/frame/fulfillment fixture comparisons matched exit
status, diagnostics, and successful LLVM output. Focused coverage checks direct
and inherited contracts plus forbidden-field and unconstrained calls. The accepted
fixture returns 42 at runtime.

Full O0 baseline/candidate wall times were 77.03/74.42 seconds and, reversing
order, 77.20/74.44 seconds; user CPU times were 76.49/73.90 and 76.65/73.89.
All four objects were byte-identical. This is 3.4–3.6% less wall time against
`d4451281` on the same current compiler source and host, using self-hosted
binaries. Logs: `build/frame-filter-full-{baseline,candidate}.log` and their
`-reverse.log` variants. Fresh bootstrap on `a5a1442b` passed five initial probes,
full compiler emission (19,108,520 bytes), byte-identical gen3/gen4 objects, and
40 identical repeat emissions (`build/frame-filter-committed-self-host.log`).
The rebuilt profiler also passed native and sampling regressions; evidence:
`build/frame-filter-native-regression.log` and `build/frame-filter-sampling-regression.log`.

## Share semantic variadic markers (2026-09-08)

Semantic declaration collection now builds a variadic-marker subset once and
shares it across module and scoped recursion. All other collection checks keep
the full annotation table. Backend variadic lookup is unchanged.
All 586 diagnostic/module/variadic comparisons matched statuses, messages, and
successful LLVM output. A strengthened nested-module rejection fixture additionally
matched both missing-required and excess-fixed argument diagnostics; the accepted
variadic fixture returned 42 at runtime.

Full O0 baseline/candidate wall times were 74.18/72.94 seconds and, reversing
order, 74.60/72.88 seconds. User CPU times were 73.67/72.48 and 74.12/72.36.
All four emitted objects were byte-identical: 1.7–2.3% less wall time against
`a5a1442b` on identical current source, with self-hosted binaries. Logs:
`build/variadic-filter-full-{baseline,candidate}.log` and their `-reverse.log`
variants. Fresh bootstrap on `43aeeb98` passed five initial probes, full compiler
emission (19,109,464 bytes), byte-identical gen3/gen4 objects, and all 40 repeat
emissions (`build/variadic-filter-committed-self-host.log`). Profiler rebuild and
native/sampling regression checks also passed (`build/variadic-filter-native-regression.log`
and `build/variadic-filter-sampling-regression.log`).

## Compact backend variadic markers (2026-09-08)

Backend declaration collection shares one variadic-marker subset across ordinary,
module, impl, and handler function declaration paths. Other backend annotation
checks, including extern handling, retain their full tables. All 674 selected
diagnostic/variadic/module/impl/effect comparisons matched exit statuses, messages,
and successful LLVM output. The real `va_list` runtime fixture printed
`value=42 word=hello` and exited successfully.

Full O0 baseline/candidate wall times were 72.96/71.48 seconds and, reversing
order, 72.94/71.36 seconds. User CPU times were 72.45/71.01 and 72.49/70.88.
All four emitted objects were byte-identical: 2.0–2.2% less wall time against
`43aeeb98` on identical current source with self-hosted binaries. Logs:
`build/backend-variadic-full-{baseline,candidate}.log` and their `-reverse.log`
variants. Fresh bootstrap on `bcb3d87b` passed five probes, full compiler emission
(19,110,200 bytes), byte-identical gen3/gen4 objects, and all 40 repeat emissions
(`build/backend-variadic-committed-self-host.log`). The rebuilt profiler also
passed native and sampling regressions (`build/backend-variadic-native-regression.log`
and `build/backend-variadic-sampling-regression.log`).

## Guard refinement mutation lookups (2026-09-08)

Mutation-position collection now queries declared changes only for contracted
mutable borrows. Nonmutable parameters never enter that table; uncontracted
mutable borrows invalidate without consulting annotations. All 394 selected
diagnostic/refinement/borrow/contract comparisons matched statuses, messages,
and successful LLVM output. A direct semantic harness additionally verified
exact invalidation diagnostics at the declared-change and unconstrained-call
sites, with none at the preserving call. It runs the public invalidation pass
on parsed source, independently of backend law-expression limitations.

Full O0 baseline/candidate wall times were 71.54/68.75 seconds and, reversing
order, 71.61/68.60 seconds. User CPU times were 70.98/68.24 and 71.03/67.99.
All four emitted objects were byte-identical: 3.9–4.2% less wall time against
`bcb3d87b` on identical current source with self-hosted binaries. Logs:
`build/refinement-lookup-full-{baseline,candidate}.log` and their `-reverse.log`
variants. Fresh bootstrap on `51abe116` passed five probes, full compiler emission
(19,110,168 bytes), byte-identical gen3/gen4 objects, and all 40 repeat emissions
(`build/refinement-lookup-committed-self-host.log`). The rebuilt profiler also
passed native and sampling regressions (`build/refinement-lookup-native-regression.log`
and `build/refinement-lookup-sampling-regression.log`).

## Compact linear-mutable rebind claims (2026-09-08)

The reassignment checker now collects its rebind-claim annotation subset once,
preserving original rows, order, and duplicates. All 387 selected diagnostic and
threading comparisons matched statuses, messages, and successful LLVM output.
A direct semantic harness verifies that the parser retains the trailing receiver
claim in `rebind ... = get ...` and that only the dropped-receiver case receives
the expected diagnostic, at its exact source line.

Full O0 baseline/candidate wall times were 68.98/66.31 seconds and, reversing
order, 69.14/66.29 seconds. User CPU times were 68.09/65.49 and 68.32/65.50.
All four emitted objects were byte-identical: 3.9–4.1% less wall time against
`51abe116` on identical current source with self-hosted binaries. Logs:
`build/rebind-filter-full-{baseline,candidate}.log` and their `-reverse.log`
variants. Fresh bootstrap on `1910e662` passed five probes, full compiler emission
(19,110,912 bytes), byte-identical gen3/gen4 objects, and all 40 repeat emissions
(`build/rebind-filter-committed-self-host.log`). Profiler rebuild and both native
and sampling regression checks passed (`build/rebind-filter-profiler-build.log`,
`build/rebind-filter-native-regression.log`, and
`build/rebind-filter-sampling-regression.log`).

Freshness rechecked on 2026-09-08: main remains at `a313a619`, an ancestor of
our dedicated compiler's `1910e662`. All ten modified source files and the
untracked chained-index fixture in main match our worktree byte-for-byte.
The branch audit includes all 11 local branch tips; other dirty worktrees
remain preserved, not silently treated as integrated changes.

## Post-rebind compiler profile (2026-09-08)

A fresh instrumented build of `1910e662`, linked with freshly generated collector
and localized runtime objects, completed the full compiler workload successfully
in 72.374 seconds. The 5 ms sampling capture contained 11,393 samples, zero
missed samples, zero dropped frames, and reported complete capture. Evidence:
`build/post-rebind-full-profile.json` and `build/post-rebind-full-profile.log`.

Leading sampled leaves were `emit_object` (516), `arena_realloc` (514),
`new_region_with_owner` (504), `mutable_ref_param_type` (411),
`packed_dynamic_row_load_value` (383), and `region_fact_parameter_has_region`
(333). These are callback-stack CPU samples, not native-PC attribution or exact
self times. A single instrumented run is not a paired throughput benchmark.
Readonly argument checking is the next candidate: it currently performs its
parameter lookup before checking whether the argument is a readonly reference.

## Gate readonly parameter lookups (2026-09-08)

Readonly argument checking now scans parameter metadata only for positional
readonly arguments that could produce its diagnostic. Overload handling stays
unchanged. All 392 selected diagnostic/readonly/overload/borrow comparisons
matched status, diagnostic output, and successful LLVM output. A focused direct
semantic harness additionally checks the exact rejected-call diagnostic and
the readonly-overload and named-argument exemptions.

Full O0 baseline/candidate wall times were 66.05/65.02 seconds, and 66.48/65.01
seconds in reverse execution order. User CPU times were 65.41/64.21 and
65.66/64.33 seconds. All four objects were byte-identical: 1.6–2.2% less wall
time than `1910e662`, using self-hosted binaries on identical current source.
Evidence: `build/readonly-lookup-full-{baseline,candidate}.log` and their
`-reverse.log` variants. Fresh bootstrap of committed `2eef943b` passed on
2026-09-09: five probes, full compiler emission (19,110,864 bytes), byte-identical
generation 3/4 objects, and all 40 repeat emissions. The profiler rebuild also
passed. Evidence: `build/readonly-lookup-committed-self-host.log` and
`build/readonly-lookup-profiler-build.log`. Native and sampling regressions also
passed (`build/readonly-lookup-native-regression.log` and
`build/readonly-lookup-sampling-regression.log`).

## Compact preserves annotations (2026-09-09)

The preserves checker now retains only its paired root/field rows and the three
row kinds used by its shared frame-change lookup. Original order and duplicates
remain intact, including fields contributed through frame-law fulfillment.
All 389 selected diagnostic/frame/fulfillment comparisons matched status,
diagnostics, and successful LLVM output. A direct semantic harness verifies
exact direct-write and inherited-write diagnostics inside a module, with no
diagnostic for an unrelated preserved field.

Full O0 baseline/candidate wall times were 64.71/63.28 seconds and, reversing
execution order, 64.76/63.22 seconds. User CPU times were 64.23/62.81 and
64.30/62.76 seconds. All four emitted objects were byte-identical: 2.2–2.4%
less wall time than `2eef943b` using self-hosted binaries on identical current
source. Evidence: `build/preserves-filter-full-{baseline,candidate}.log` and
their `-reverse.log` variants. Fresh bootstrap of committed `520d4572` passed:
five probes, full compiler emission (19,111,904 bytes), byte-identical generation
3/4 objects, and all 40 repeat emissions. Profiler rebuild and native/sampling
regressions also passed. Evidence: `build/preserves-filter-committed-self-host.log`,
`build/preserves-filter-profiler-build.log`,
`build/preserves-filter-native-regression.log`, and
`build/preserves-filter-sampling-regression.log`.

## Compact frame-law conformance annotations (2026-09-09)

Frame-law conformance now receives only law-field and paired fulfillment
law/subject rows, preserving their order and duplicates. Sibling law validation
still sees the full table, and value-position checks still run without fulfills
clauses. All 390 selected diagnostic/frame/fulfillment/law comparisons matched
status, diagnostics, and successful LLVM output. A focused semantic harness
checks subject selection, changes/preserves fields, and a frame-law value test
in a function without a fulfillment clause.

Full O0 baseline/candidate wall times were 63.09/61.14 seconds and, reversing
order, 63.41/61.08 seconds. User CPU times were 62.65/60.71 and 62.77/60.61.
All four objects were byte-identical: 3.1–3.7% less wall time than `520d4572`
with self-hosted binaries on identical current source. Evidence:
`build/frame-conformance-full-{baseline,candidate}.log` and their `-reverse.log`
variants. Fresh bootstrap of committed `b22adad5` passed: five probes, full
compiler emission (19,113,008 bytes), byte-identical generation 3/4 objects, and
all 40 repeat emissions. Profiler rebuild and native/sampling regressions also
passed. Evidence: `build/frame-conformance-committed-self-host.log`,
`build/frame-conformance-profiler-build.log`,
`build/frame-conformance-native-regression.log`, and
`build/frame-conformance-sampling-regression.log`.

## Post-frame-conformance compiler profile (2026-09-09)

A freshly instrumented `b22adad5` completed the full compiler workload in
67.361 seconds. The 5 ms capture contained 10,899 samples, zero missed samples,
zero dropped frames, and reported complete capture. Evidence:
`build/post-frame-full-profile.json` and `build/post-frame-full-profile.log`.

Leading sampled leaves were `new_region_with_owner` (514), `emit_object` (501),
`arena_realloc` (489), `packed_dynamic_row_load_value` (382),
`region_fact_parameter_has_region` (367), `ae_effect_declared` (292), and
`note_local_type` (290). These are callback-stack CPU samples, not native-PC
attribution or exact self times. This single instrumented run does not establish
a paired throughput gain; use the preceding controlled benchmarks for that.

## Index region-fact names (2026-09-09)

Region forwarding now uses name buckets with exact-name collision checks and
source-ordered chains. Existing owner precedence, first top-level fallback,
arity filtering, and live fact updates remain intact. A direct backend test
exercises these cases, including two colliding names. All 606 selected
diagnostic/region/module/overload/packed comparisons matched statuses,
diagnostics, and successful LLVM output.

The direct test also exposed an existing compiler bug: implicit packed-store
initialization could receive a null arena. The independent fix `a6810bfb` and
its focused regression precede the index. Both performance binaries include
that fix; the baseline was built from a detached checkout of `a6810bfb`.

Full O0 baseline/candidate wall times were 61.29/59.02 seconds and, reversing
order, 61.53/58.76 seconds. User CPU times were 60.60/58.20 and 60.74/58.06.
All four objects were byte-identical: 3.7–4.5% less wall time with self-hosted
binaries on identical current source. Evidence:
`build/region-index-full-{baseline,candidate}.log` and their `-reverse.log`
variants. Fresh bootstrap of committed `d4178fe7` passed: five probes, full
compiler emission (19,116,424 bytes), byte-identical generation 3/4 objects, and
all 40 repeat emissions. Profiler rebuild and native/sampling regressions also
passed. Evidence: `build/region-index-committed-self-host.log`,
`build/region-index-profiler-build.log`, `build/region-index-native-regression.log`,
and `build/region-index-sampling-regression.log`.

## Cumulative full-compiler comparison through region indexing (2026-09-09)

The archived self-hosted `2f8b2180` compiler and current self-hosted `d4178fe7`
compiled identical current compiler source using the same runtime and output
path. Baseline/current wall times were 163.46/58.97 seconds; in reverse order,
they were 163.51/59.18 seconds. User CPU times were 162.18/58.19 and
162.18/58.42 seconds. All four emitted objects were byte-identical.

Across the two timing orders this is approximately **2.77× compilation
throughput**, or **63.9% less wall time**, on this full-compiler O0 workload.
This is a direct cumulative comparison, not a sum of individual percentages;
it does not establish profiler overhead or performance on other workloads.
Evidence: `build/cumulative-index-full-{baseline,current}.log` and their
`-reverse.log` variants.

## Compact rebind-claim validation rows (2026-09-09)

The false-claim checker now collects only claim annotations once per pass,
preserving source order and duplicates. All 389 selected diagnostic/rebind/lmut/
claim/threading comparisons matched status, diagnostics, and successful LLVM
output. A focused semantic test verifies ordered false-claim diagnostics and
acceptance of genuine threading and ordinary calls.

Full O0 baseline/candidate wall times were 58.90/57.57 seconds and, reversing
order, 59.12/57.22 seconds. User CPU times were 58.28/56.72 and 58.24/56.54.
All four objects were byte-identical: 2.3–3.2% less wall time than `d4178fe7`
with self-hosted binaries on identical source. Evidence:
`build/claim-filter-full-{baseline,candidate}.log` and their `-reverse.log`
variants. Fresh bootstrap of committed `2a64005f` passed: five probes, full
compiler emission (19,117,352 bytes), byte-identical generation 3/4 objects, and
all 40 repeat emissions. Profiler rebuild and native/sampling regressions also
passed. Evidence: `build/claim-filter-committed-self-host.log`,
`build/claim-filter-profiler-build.log`, `build/claim-filter-native-regression.log`,
and `build/claim-filter-sampling-regression.log`.

## Post-claim-filter compiler profile (2026-09-09)

A fresh instrumented `2a64005f` completed the full compiler workload in 63.512
seconds. The 5 ms capture retained 10,521 samples, with zero missed samples,
zero dropped frames, and complete capture. Evidence:
`build/post-claim-full-profile.json` and `build/post-claim-full-profile.log`.

Leading sampled leaves were `emit_object` (513), `arena_realloc` (474),
`new_region_with_owner` (470), `packed_dynamic_row_load_value` (361),
`ae_effect_declared` (305), `note_local_type` (299), `ens_check_return_bool`
(267), and `decl_line_is_generic` (245). These are callback-stack CPU samples,
not native-PC attribution or exact self times. The single instrumented run is
hotspot evidence, not a controlled throughput or profiler-overhead comparison.

## Cache template lines during declaration (2026-09-09)

The function declaration pass now collects ordinary generic and errorset-only
template lines once, excluding bound-only rows and retaining generated-typestate
exceptions. All 613 selected diagnostic/generic/errorset/typestate/overload/module
comparisons matched status, diagnostics, and successful LLVM output. A direct
metadata test verifies duplicates, ordering, errorset inclusion, and bound-row
and unrelated-row exclusion.

Full O0 baseline/candidate wall times were 56.81/55.55 seconds and, reversing
order, 56.96/55.57 seconds. User CPU times were 56.25/55.05 and 56.43/55.09.
All four objects were byte-identical: 2.2–2.4% less wall time than `2a64005f`
with self-hosted binaries on identical source. Evidence:
`build/template-lines-full-{baseline,candidate}.log` and their `-reverse.log`
variants. Fresh bootstrap of committed `e7674ecb` passed: five probes, full
compiler emission (19,118,856 bytes), byte-identical generation 3/4 objects, and
all 40 repeat emissions. Profiler rebuild and native/sampling regressions also
passed. Evidence: `build/template-lines-committed-self-host.log`,
`build/template-lines-profiler-build.log`, `build/template-lines-native-regression.log`,
and `build/template-lines-sampling-regression.log`.

## Cache template lines during body emission (2026-09-09)

Body emission now collects template lines once and reuses them in its top-level,
module, and handler paths, retaining generated-typestate exceptions. All 650
selected diagnostic/generic/errorset/typestate/overload/module/handler comparisons
matched status, diagnostics, and successful LLVM output. The direct template
metadata smoke also passed.

Full O0 baseline/candidate wall times were 55.54/54.31 seconds and, reversing
order, 55.70/54.23 seconds. User CPU times were 55.12/53.85 and 55.25/53.79.
All four objects were byte-identical: 2.2–2.6% less wall time than `e7674ecb`
with self-hosted binaries on identical source. Evidence:
`build/template-bodies-full-{baseline,candidate}.log` and their `-reverse.log`
variants. Fresh bootstrap of committed `78c55f54` passed: five probes, full
compiler emission (19,118,928 bytes), byte-identical generation 3/4 objects, and
all 40 repeat emissions. Profiler rebuild and native/sampling regressions also
passed. Evidence: `build/template-bodies-committed-self-host.log`,
`build/template-bodies-profiler-build.log`, `build/template-bodies-native-regression.log`,
and `build/template-bodies-sampling-regression.log`.

## Compact effect-template filtering (2026-09-09)

Recursive effect-template filtering now receives only template annotations,
retaining exact name/line matching and module/scoped traversal. All 669 selected
diagnostic/effect/handler/module/template comparisons matched status, diagnostics,
and successful LLVM output. A focused test verifies same-name overload retention
and unchanged member order when annotations are empty.

Full O0 baseline/candidate wall times were 54.09/53.02 seconds and, reversing
order, 54.58/52.94 seconds. User CPU times were 53.61/52.31 and 53.83/52.29.
All four objects were byte-identical: 2.0–3.0% less wall time than `78c55f54`
with self-hosted binaries on identical source. Evidence:
`build/effect-template-filter-full-{baseline,candidate}.log` and their
`-reverse.log` variants. Fresh bootstrap of committed `2ec59777` passed: five
probes, full compiler emission (19,119,928 bytes), byte-identical generation 3/4
objects, and all 40 repeat emissions. Profiler rebuild and native/sampling
regressions also passed. Evidence:
`build/effect-template-filter-committed-self-host.log`,
`build/effect-template-filter-profiler-build.log`,
`build/effect-template-filter-native-regression.log`, and
`build/effect-template-filter-sampling-regression.log`.

## Cumulative compiler throughput through template filtering (2026-09-09)

Archived self-hosted `2f8b2180` versus self-hosted `2ec59777`, compiling
identical current compiler source at O0 with the same runtime and output path:
baseline/current wall times 163.02/52.96 seconds; reverse-order
current/baseline 52.66/163.35 seconds. User CPU times were 162.00/52.51
and 52.27/162.52 respectively. All four emitted objects were byte-identical,
and the comparison chain exited zero. Mean wall time fell from 163.185 to
52.81 seconds: 3.09× throughput, or 67.6% less wall time. This is compiler
throughput on this workload, not a profiler-overhead measurement or a claim
about all Elisa programs. Evidence: `build/cumulative-template-full-*.log`.

## Compact effect-row validation annotations (2026-09-09)

Effect declaration/block validation now receives only its lookup dependencies:
effect and permission declarations, permission parameters and aliases, operation
and member rows, and effect-reference positions. Alias discovery still scans
the complete original table; retained row order and duplicates are unchanged.
All 487 diagnostic/effect/permission/alias comparisons matched statuses, logs,
and successful LLVM output. A focused lookup regression also passed.

Self-hosted baseline `2ec59777` and candidate full O0 compilation took
52.80/51.20 seconds; reversing order, candidate/baseline took 51.01/53.03.
User CPU times were 52.36/50.53 and 50.52/52.32. All four objects were
byte-identical and the benchmark chain exited zero: 3.0–3.8% less wall time
on this workload. Evidence: `build/effect-row-full-*.log`.
Fresh bootstrap of committed `88362a1d` passed five probes, full compiler
emission (19,120,960 bytes), byte-identical generation 3/4 objects, and all
40 repeat emissions. Profiler rebuild and native/sampling regressions passed;
the complete validation chain exited zero. Evidence:
`build/effect-row-committed-self-host.log`, `build/effect-row-profiler-build.log`,
`build/effect-row-native-regression.log`, and `build/effect-row-sampling-regression.log`.

## Compact ensures-return annotations (2026-09-09)

The recursive return-type validator now receives only parser rows whose name is
`__ensures_return_bool`; unrelated annotation rows are not rescanned for every
function. A focused filter regression and 485 semantic fixture comparisons
matched exactly, including successful LLVM output.

Self-hosted baseline `88362a1d` and candidate full O0 compilation took
51.66/50.25 seconds; reversing order, candidate/baseline took 50.17/51.99.
User CPU times were 50.92/49.24 and 49.31/50.99. All four objects were
byte-identical and the chain exited zero: 2.8–3.5% less wall time on this
workload. Evidence: `build/ens-return-bool-full-*.log`.
Fresh bootstrap and profiler regressions for committed `8734d199` are recorded
below.

Fresh bootstrap of committed `8734d199` passed five probes, full compiler
emission (19,121,032 bytes), byte-identical generation 3/4 objects, and all
40 repeat emissions. The profiler rebuild, native regression, and native
sampling regression also passed; the chain exited zero. Evidence:
`build/ens-return-bool-committed-self-host.log`,
`build/ens-return-bool-profiler-build.log`,
`build/ens-return-bool-native-regression.log`, and
`build/ens-return-bool-sampling-regression.log`.

## Compact contract-marker annotations (2026-09-09)

`collect_contract_requires` and `collect_contract_ensures` now receive one
shared, order-preserving subset containing only `__contract_decl` rows. This
removes a full annotation-table scan from both recursive walks while retaining
contract identity and duplicate rows. The focused filter regression and 485
contract/effect/diagnostic comparisons matched statuses, diagnostics, and
successful LLVM output.

Self-hosted baseline `8734d199` and candidate full O0 compilation took
49.80/47.19 seconds; reversing order, candidate/baseline took 47.40/50.11.
User CPU times were 49.17/46.58 and 46.70/49.21. All four objects were
byte-identical and the chain exited zero: 5.2–5.4% less wall time on this
workload. Evidence: `build/contract-filter-full-*.log`.

Fresh bootstrap of committed `a86cc9e4` passed five probes, full compiler
emission (19,121,848 bytes), byte-identical generation 3/4 objects, and all
40 repeat emissions. The profiler rebuild, native regression, and native
sampling regression also passed; the complete chain exited zero. Evidence:
`build/contract-filter-committed-self-host.log`,
`build/contract-filter-profiler-build.log`,
`build/contract-filter-native-regression.log`, and
`build/contract-filter-sampling-regression.log`.

## Filter lambda error-family annotations and remove duplicate disjoint scans (2026-09-09)

Lambda-raise conformance now receives only `__error_set_family` rows. The
disjointness expression walker also no longer visits parenthesized expressions
twice. The focused error-family regression and all 560 fixture comparisons
matched statuses, diagnostics, and successful LLVM output; the broader corpus
also covers the disjointness cleanup.

Self-hosted baseline `a86cc9e4` and candidate full O0 compilation took
47.46/46.21 seconds; reversing order, candidate/baseline took 46.16/47.75.
User CPU times were 46.67/45.28 and 45.38/46.76. All four objects were
byte-identical and the chain exited zero: 2.6–3.3% less wall time on this
workload. Evidence: `build/error-family-full-*.log`.

Fresh bootstrap of committed `9bf231e6` passed five probes, full compiler
emission (19,122,296 bytes), byte-identical generation 3/4 objects, and all
40 repeat emissions. The profiler rebuild, native regression, and native
sampling regression also passed; the complete chain exited zero. Evidence:
`build/error-family-committed-self-host.log`,
`build/error-family-profiler-build.log`,
`build/error-family-native-regression.log`, and
`build/error-family-sampling-regression.log`.

## Consolidate the disjoint freshness statement walk (2026-09-09)

The fresh-variable collector now uses one exhaustive statement match instead
of dispatching through seven sequential matches for every statement. The
change preserves the existing recursive walk and variable bookkeeping. All
560 Elisa fixture comparisons matched statuses, diagnostics, and successful
LLVM output byte-for-byte.

Self-hosted baseline `9bf231e6` and candidate full O0 compilation took
46.01/45.74 seconds; reversing order, candidate/baseline took 45.81/45.97.
User CPU times were 45.38/45.12 and 45.18/45.35. The paired means are
45.99 seconds for baseline and 45.78 seconds for candidate (0.47% less wall
time and 0.47% less user CPU); retired instructions fell by 0.28%. All four
objects were byte-identical and the chain exited zero. Evidence:
`build/disjoint-collector-full-*.log`.

Fresh bootstrap of committed `e34e3af1` passed five probes, full compiler
emission (19,122,040 bytes), byte-identical generation 3/4 objects, and all
40 repeat emissions. The profiler rebuild, native regression, and native
sampling regression also passed; the complete chain exited zero. Evidence:
`build/disjoint-collector-committed-self-host.log`,
`build/disjoint-collector-committed-profiler-build.log`,
`build/disjoint-collector-committed-native-regression.log`, and
`build/disjoint-collector-committed-sampling-regression.log`.

## Consolidate the disjoint expression walk (2026-09-09)

The disjointness expression walker now dispatches through one exhaustive
expression match instead of repeatedly matching the same expression against
sequential groups of variants. Call handling keeps its early-return behavior,
and all child-expression recursion remains in the same traversal order. All
560 Elisa fixture comparisons matched statuses, diagnostics, and successful
LLVM output byte-for-byte.

Self-hosted baseline `e34e3af1` and candidate full O0 compilation took
45.71/45.64 seconds; reversing order, candidate/baseline took 45.60/45.92.
User CPU times were 45.12/45.04 and 45.00/45.27. The paired means are
45.815 seconds for baseline and 45.620 seconds for candidate (0.43% less wall
time and 0.39% less user CPU); retired instructions fell by 0.62% and cycles
by 0.38%. All four objects were byte-identical and the chain exited zero.
Evidence: `build/disjoint-expr-full-*.log`.

Fresh bootstrap of committed `f56a0487` passed five probes, full compiler
emission (19,121,712 bytes), byte-identical generation 3/4 objects, and all
40 repeat emissions. The profiler rebuild, native regression, and native
sampling regression also passed; the complete chain exited zero. Evidence:
`build/disjoint-expr-committed-self-host.log`,
`build/disjoint-expr-committed-profiler-build.log`,
`build/disjoint-expr-committed-native-regression.log`, and
`build/disjoint-expr-committed-sampling-regression.log`.

## Flatten extern declarations for firm checks (2026-09-09)

Firm-argument checking now flattens nested extern declarations once per file
and supplies that private list to its extern ABI and protocol-state queries.
Calls no longer rescan unrelated functions and scopes for every argument,
while duplicate extern declarations remain present so conflicting overloads
still conservatively suppress the narrow mismatch diagnostic. All 560 Elisa
fixture comparisons matched statuses, diagnostics, and successful LLVM output
byte-for-byte.

Self-hosted baseline `f56a0487` and candidate full O0 compilation took
45.72/44.92 seconds; reversing order, candidate/baseline took 44.87/45.68.
User CPU times were 45.16/44.38 and 44.35/45.07. The paired means are
45.70 seconds for baseline and 44.895 seconds for candidate (1.76% less wall
time and 1.66% less user CPU); retired instructions fell by 1.10% and cycles
by 1.69%. All four objects were byte-identical and the chain exited zero.
Evidence: `build/extern-declarations-full-*.log`.

Fresh bootstrap of committed `ea8570a7` passed five probes, full compiler
emission (19,123,800 bytes), byte-identical generation 3/4 objects, and all
40 repeat emissions. The profiler rebuild, native regression, and native
sampling regression also passed; the complete chain exited zero. Evidence:
`build/extern-declarations-committed-self-host.log`,
`build/extern-declarations-committed-profiler-build.log`,
`build/extern-declarations-committed-native-regression.log`, and
`build/extern-declarations-committed-sampling-regression.log`.

## Consolidate the disjoint statement walk (2026-09-09)

The disjointness statement walker now dispatches through one exhaustive match
instead of repeatedly matching the same statement against sequential variant
groups. It preserves the existing recursive traversal and all fresh/dead/seen
bookkeeping. All 560 Elisa fixture comparisons matched statuses, diagnostics,
and successful LLVM output byte-for-byte.

Self-hosted baseline `ea8570a7` and candidate full O0 compilation took
44.86/44.60 seconds; reversing order, candidate/baseline took 44.80/45.05.
User CPU times were 44.32/44.08 and 44.26/44.42. The paired means are
44.955 seconds for baseline and 44.700 seconds for candidate (0.57% less wall
time and 0.45% less user CPU); retired instructions fell by 0.45% and cycles
by 0.46%. All four objects were byte-identical and the chain exited zero.
Evidence: `build/disjoint-statements-full-*.log`.

Fresh bootstrap of committed `204138ff` passed five probes, full compiler
emission (19,123,408 bytes), byte-identical generation 3/4 objects, and all
40 repeat emissions. The profiler rebuild, native regression, and native
sampling regression also passed; the complete chain exited zero. Evidence:
`build/disjoint-statements-committed-self-host.log`,
`build/disjoint-statements-committed-profiler-build.log`,
`build/disjoint-statements-committed-native-regression.log`, and
`build/disjoint-statements-committed-sampling-regression.log`.

## Index errorset parameter annotations (2026-09-09)

The catch-parameter checker now builds a compact parallel index of
`__errorset_param` annotations once per file. Function checks consult that
index instead of scanning the complete parser annotation table for every
function. The source-view ownership and first-match behavior are unchanged.
All 560 Elisa fixture comparisons matched statuses, diagnostics, and
successful LLVM output byte-for-byte.

Self-hosted baseline `ea8570a7` and candidate full O0 compilation took
44.78/43.38 seconds; reversing order, candidate/baseline took 43.52/44.81.
User CPU times were 44.26/42.89 and 42.91/44.20. The paired means are
44.795 seconds for baseline and 43.450 seconds for candidate (3.00% less wall
time and 3.01% less user CPU); retired instructions fell by 3.03% and cycles
by 3.04%. All four objects were byte-identical and the chain exited zero.
Evidence: `build/cpb-index-full-*.log`.

Fresh bootstrap of committed `bb8c39bb` passed five probes, full compiler
emission (19,124,224 bytes), byte-identical generation 3/4 objects, and all
40 repeat emissions. The profiler rebuild, native regression, and native
sampling regression also passed; the complete chain exited zero. Evidence:
`build/cpb-index-committed-self-host.log`,
`build/cpb-index-committed-profiler-build.log`,
`build/cpb-index-committed-native-regression.log`, and
`build/cpb-index-committed-sampling-regression.log`.

## Index changes target annotations (2026-09-09)

The `changes`-target checker now builds a compact owner/name index for root
annotations once per file. Each function checks only those rows instead of
rescanning the complete annotation table, while row order and duplicate
diagnostics remain unchanged. All 560 Elisa fixture comparisons matched
statuses, diagnostics, and successful LLVM output byte-for-byte.

Self-hosted baseline `bb8c39bb` and candidate full O0 compilation took
43.62/42.32 seconds; reversing order, candidate/baseline took 42.54/43.63.
User CPU times were 43.03/41.80 and 41.94/43.01. The paired means are
43.625 seconds for baseline and 42.430 seconds for candidate (2.74% less wall
time and 2.67% less user CPU); retired instructions fell by 3.15% and cycles
by 2.63%. All four objects were byte-identical and the chain exited zero.
Evidence: `build/changes-roots-full-*.log`.

Fresh bootstrap of committed `b1c84fac` passed five probes, full compiler
emission (19,125,168 bytes), byte-identical generation 3/4 objects, and all
40 repeat emissions. The profiler rebuild, native regression, and native
sampling regression also passed; the complete chain exited zero. Evidence:
`build/changes-roots-committed-self-host.log`,
`build/changes-roots-committed-profiler-build.log`,
`build/changes-roots-committed-native-regression.log`, and
`build/changes-roots-committed-sampling-regression.log`.

## Index changes field annotations (2026-09-09)

The frame-write checker now indexes `changes` field rows once per file and
looks up each function in that compact index. It preserves field order,
duplicate rows, and the existing conservative field-name semantics. All 560
Elisa fixture comparisons matched statuses, diagnostics, and successful LLVM
output byte-for-byte.

Self-hosted baseline `b1c84fac` and candidate full O0 compilation took
42.65/41.62 seconds; reversing order, candidate/baseline took 41.69/42.70.
User CPU times were 42.05/41.03 and 41.08/42.09. The paired means are
42.675 seconds for baseline and 41.655 seconds for candidate (2.39% less wall
time and 2.41% less user CPU); retired instructions fell by 2.15% and cycles
by 2.44%. All four objects were byte-identical and the chain exited zero.
Evidence: `build/changes-fields-full-*.log`.

Fresh bootstrap of committed `8c7b7d63` passed five probes, full compiler
emission (19,125,520 bytes), byte-identical generation 3/4 objects, and all
40 repeat emissions. The profiler rebuild, native regression, and native
sampling regression also passed; the complete chain exited zero. Evidence:
`build/changes-fields-committed-self-host.log`,
`build/changes-fields-committed-profiler-build.log`,
`build/changes-fields-committed-native-regression.log`, and
`build/changes-fields-committed-sampling-regression.log`.

## Memoize readonly-reference parameter lookups (2026-09-09)

The readonly-reference semantic pass now memoizes immutable `(callee,
argument position)` lookups and shares the cache across both readonly checks.
The cache keeps overload order and the empty-result behavior intact. All 560
Elisa fixture comparisons matched statuses, diagnostics, and successful LLVM
output byte-for-byte.

Self-hosted baseline `8c7b7d63` and candidate full O0 compilation took
41.69/41.45 seconds; reversing order, candidate/baseline took 41.57/41.69.
User CPU times were 41.18/40.94 and 40.99/41.09. The paired means are
41.690 seconds for baseline and 41.510 seconds for candidate (0.43% less wall
time and 0.41% less user CPU); retired instructions fell by 0.91% and cycles
by 0.41%. All four objects were byte-identical and the chain exited zero.
Evidence: `build/readonly-cache-fixed-full-*.log`.

Fresh bootstrap of committed `458ef52d` passed five probes, full compiler
emission (19,132,016 bytes), byte-identical generation 3/4 objects, and all
40 repeat emissions. The profiler rebuild, native regression, and native
sampling regression also passed; the complete chain exited zero. Evidence:
`build/readonly-cache-fixed-committed-self-host.log`,
`build/readonly-cache-fixed-committed-profiler-build.log`,
`build/readonly-cache-fixed-committed-native-regression.log`, and
`build/readonly-cache-fixed-committed-sampling-regression.log`.

## Post-semantic-index profile (2026-09-09)

The fresh profile after `458ef52d` completed successfully in 47.319 seconds
with 8,056 samples, zero missed samples, zero dropped records, 8,062 valid
frames, and 3,111,324 valid capture bytes. The leading leaf counts were
`arena_realloc` 550, `emit_object` 522, `new_region_with_owner` 458,
`packed_dynamic_row_load_value` 315, `note_local_type` 285,
`disjoint_collect_fresh` 221, `effect_template_row_is_abstract` 164,
`check_effect_law_fulfillment_decls` 160, `positional_construction_expression`
157, and `mutable_ref_param_type` 150. This is callback-stack attribution,
not native-PC self-time; the capture was complete and exact. Evidence:
`build/post-readonly-cache-full-profile.json`.

## Reuse the packed-row LLVM index buffer (2026-09-09)

The packed dynamic-row loader now allocates its one-element LLVM index buffer
once per value instead of once for every payload word. It also reuses the
already-resolved LLVM value type and word type throughout the loop. This keeps
the emitted LLVM unchanged while removing repeated compiler-side arena work.
All 560 Elisa fixture comparisons matched statuses, diagnostics, and successful
LLVM output byte-for-byte.

Self-hosted baseline `458ef52d` and candidate full O0 compilation took
38.70/38.54 seconds; reversing order, candidate/baseline took 38.55/38.61.
User CPU times were 38.17/38.06 and 38.04/38.11. The paired means are
38.655 seconds for baseline and 38.545 seconds for candidate (0.28% less wall
time and 0.24% less user CPU); retired instructions fell by 0.02% and cycles
by 0.25%. All four objects were byte-identical and the chain exited zero.
These measurements used `-emit llvm`; they measure LLVM emission, excluding
native object emission. They must not be compared directly with the preceding
41.510-second native-object benchmark. The small difference from two pairs is
preliminary evidence, not a statistically established speedup. The timing logs
are in the compiler worktree: `build/packed-index-{baseline,candidate}-{a,b}.log`.

Fresh bootstrap of committed `a9bc2f25` passed five probes, full compiler
emission (19,131,416 bytes), byte-identical generation 3/4 objects, and all 40
repeat emissions. The profiler rebuild, native regression, and native sampling
regression also passed; the complete chain exited zero. Evidence:
`build/packed-index-committed-self-host.log`,
`build/packed-index-committed-profiler-build.log`,
`build/packed-index-committed-native-regression.log`, and
`build/packed-index-committed-sampling-regression.log`.

## Broad regression checkpoint (2026-09-09)

Validation correction: the rejected effect-identity helper experiment was
originally compared against the stage0-built seed. The unchanged self-hosted
generation also emits the additional line-14 diagnostic in
`darray_element_mismatch.pos.elisa`. Comparing the preserved candidate against
`build/self_host_gen2/elisac-stage1-gen2` instead passed all 560 fixtures,
including identical diagnostics, statuses, and successful LLVM output (exit 0;
compiler-worktree evidence `build/.effect-corrected-parity.DKfEP0`). Thus the
earlier mismatch does not establish a regression caused by that optimization.
The experiment remains uncommitted: the identity table also contains the
internal `__try_lexical_module` marker, which needs separate handling before
it can replace declaration membership checks. Performance comparisons must
use matching compiler generations and emission modes.

After compiler `2ec59777`, the full `make test` log reached its final
`process-group cleanup OK` check, and the observed make process exited.
The log includes successful bootstrap fixed-point/repeat checks, native and
sampling regressions, cache and identity checks, protocol/property tests,
collector sanitizer checks, recovery, budgets, and process cleanup.
No failure is reported in `build/post-optimizations-full-test.log`.
The original process exit-status handle was not recovered, so this records
the completed test-log evidence rather than an independently captured exit code.

## Effect fulfillment metadata filtering (2026-09-09)

Compiler commit `747d8616` filters fulfillment annotations once per file before
walking function declarations, preserving annotation order and duplicate clauses.
This removes unrelated metadata from repeated per-function scans.

The matching self-hosted baseline (`a9bc2f25`) and candidate compiled
`src/driver/elisac.elisa` with `-O0` to **native objects**, sequentially in
baseline/candidate/candidate/baseline order with `DYLD_SHARED_REGION=avoid`.
Elapsed times were baseline 41.40/42.35s and candidate 40.69/41.15s:
means 41.875s and 40.920s (2.28% observed reduction). Retired instructions
averaged 682.451 billion versus 660.944 billion (3.15% reduction).
All four native objects were byte-identical. Two pairs are preliminary timing
evidence, not a statistically established speedup. Logs are in the compiler
worktree at `build/effect-law-{baseline,candidate}-{a,b}.log`.

All 560 fixture/breadth comparisons passed with matching exit statuses,
diagnostics, and successful LLVM outputs (exit 0;
`build/.effect-law-parity.nkVldT`). The focused Elisa regression
`test/parity/effect_law_filter_smoke.elisa` also passed: duplicate clauses,
diagnostic ordering, nested modules, composite laws, accepted fulfillments,
and unconstrained functions.

Promotion gates passed (captured exit 0): fresh compiler seed and manifest,
all 11 local branch tips included, self-hosting stages A (5/5), B (19,132,192
bytes), C (byte-identical fixed point), D (40 repeat objects), profiler rebuild,
native regression, and sampling regression. Profiler-worktree logs are
`build/effect-law-committed-{seed,self-host,profiler-build,native-regression,sampling-regression}.log`.
Existing uncommitted worktree changes were preserved and remain listed in the
integration ledger; branch ancestry does not mean every uncommitted edit is merged.

### Rejected lazy grant collection experiment

After `747d8616`, collecting effect grants only upon the first matching law
obligation did not improve full-compiler native-object emission. Sequential
baseline/candidate/candidate/baseline elapsed times were 40.75/40.89/41.06/41.09s
(baseline mean 40.920s, candidate 40.975s). Retired instructions were effectively
unchanged: means 661.126 billion and 661.046 billion. All four output objects
were byte-identical. This small sample supports neither a useful speedup nor
a meaningful slowdown; the source change was reverted instead of retained.
Compiler-worktree logs: `build/effect-law-lazy-{baseline,candidate}-{a,b}.log`.

### Fresh profile after fulfillment filtering

`build/post-effect-law-full-profile.json` captures committed compiler `747d8616`
compiling its own source to a native object at `-O0`. The function-instrumented
prebuilt target used the existing collector/runtime objects from the preceding
packed-index capture, which were not changed by the semantic-only optimization.
The capture succeeded in 46.761s (45.537s user CPU), with 8,310 samples at a
5,000-microsecond requested period, zero missed samples or dropped frames,
8,316 valid frames, and 3,238,911 valid capture bytes. Capture/detail were complete.

Leading instrumented-stack leaves were `emit_object` (545), `arena_realloc`
(471), `new_region_with_owner` (443), `packed_dynamic_row_load_value` (307),
`note_local_type` (286), `effect_template_row_is_abstract` (198),
`disjoint_collect_fresh` (194), `disjoint_scan_expr` (180), and
`callable_error_family` (173). These are callback-stack samples, not native-PC
self times; one capture does not establish per-function speedups. Allocation,
packed-row code generation, and repeated semantic lookups remain optimization
targets rather than evidence that compiler performance is finished.

The initial launch stopped at the timestamp-based freshness check after the
rejected experiment was reverted. With source verified identical to the commit,
the capture used `ELISA_ALLOW_STALE_STAGE1=1`. The ordinary compiler seed and
manifest were subsequently refreshed successfully without this override
(`build/post-effect-law-restored-seed.log`).

## Declared effect-family index (2026-09-09)

Compiler `befe4994` records effect declaration names in a parser-owned list and
uses it for abstract-row classification instead of scanning all annotation
metadata. The list is populated only by actual effect declarations. Internal
lexical identities therefore cannot become effects by accident; real effects
using the internal marker's spelling remain supported.

Matching self-hosted baseline `747d8616` and candidate compiled the same current
compiler source with `-O0` to native objects, sequentially in
baseline/candidate/candidate/baseline order. Wall times were
40.33/39.56/39.35/40.57s: baseline mean 40.450s and candidate 39.455s
(2.46% observed reduction). Mean retired instructions fell from 661.053 billion
to 640.257 billion (3.15%). All four objects were byte-identical. Two timing
pairs remain preliminary evidence rather than a statistically established
speedup. Compiler-worktree logs:
`build/effect-declaration-index-{baseline,candidate}-{a,b}.log`.

All 560 fixture/breadth comparisons passed, including matching statuses,
diagnostics, and successful LLVM output (exit 0;
`build/.effect-declaration-index-parity.lja7Mj`). The Elisa regression
`test/parity/effect_declaration_index_smoke.elisa` passed generic/qualified
membership, missing names, internal-only markers, and an actual declaration
with the marker spelling.

Promotion checks passed with captured exit 0: fresh seed; manifest/toolchain/ABI
validation; all 11 local branch tips included; self-hosting A (5/5), B
(19,132,544 bytes), C (byte-identical fixed point), D (40 identical repeats);
profiler rebuild; native and sampling regressions. Profiler-worktree logs:
`build/effect-declaration-index-committed-{seed,self-host,profiler-build,native-regression,sampling-regression}.log`.
Existing uncommitted changes in other worktrees remain preserved and reported
by the integration ledger.

### Rejected per-try resolution reuse experiment

After `befe4994`, an experiment reused the first fallibility query and passed
the enclosing function/module/qualifier into propagation checking. Sequential
native-object baseline/candidate/candidate/baseline elapsed times were
38.65/39.05/39.30/38.74s (means 38.695s baseline and 39.175s candidate).
Instruction means were effectively unchanged: 640.056 billion baseline versus
640.014 billion candidate. All four native objects were byte-identical.
The two-pair result showed no useful gain, so the source change was reverted;
it is not part of the active compiler. Evidence in the compiler worktree:
`build/try-resolution-reuse-{baseline,candidate}-{a,b}.log`.
The restored source matched Git exactly, and the compiler seed/manifest was
refreshed successfully (`build/try-resolution-restored-seed.log` in the profiler
worktree). This result argues against treating duplicated `try` setup queries
as a substantial full-compiler bottleneck; it does not rule out improving the
underlying callable-family scan or its data layout.

## Single-pass callable-family fallback (2026-09-09)

Compiler `200de8b0` retains the first unscoped fallback while looking for a
scope-matched callable error family. It removes the second whole-table pass
without changing scope preference, metadata exclusions, or first-match order.
A separate presence flag preserves an empty first matching row.

Four sequential native-object runs in baseline/candidate/candidate/baseline
order against matching self-hosted `befe4994` measured elapsed seconds
38.61/39.09/38.34/38.65. Means were 38.630s baseline and 38.715s candidate:
**no demonstrated elapsed-time improvement**. User CPU means were 38.240s
versus 38.020s. Retired instructions fell consistently from a mean of 640.026
billion to 631.500 billion (1.33%). All four objects were byte-identical.
This is retained as reduced compiler work, not a statistically established
wall-time speedup. Compiler-worktree evidence:
`build/callable-fallback-{baseline,candidate}-{a,b}.log`.

All 560 fixture/breadth comparisons passed with identical statuses,
diagnostics, and successful LLVM output (exit 0;
`build/.callable-fallback-parity.hv9qsq`). The focused Elisa test
`test/parity/callable_family_fallback_smoke.elisa` passed scoped/qualified
selection, fallback order, metadata exclusions, missing names, an empty first
fallback, and empty input.

Promotion checks passed (captured exit 0): seed and manifest; all 11 local
branch tips included; self-host stages A (5/5), B (19,131,984 bytes), C
(byte-identical fixed point), D (40 identical repeats); profiler rebuild;
native and sampling regressions. Profiler-worktree logs:
`build/callable-fallback-committed-{seed,self-host,profiler-build,native-regression,sampling-regression}.log`.

## Native-stack cross-check (2026-09-09)

Profiler text and HTML reports now surface this attribution limit directly,
for both live captures and saved reports (including zero-sample captures):
uninstrumented runtime/foreign work may be charged to the last instrumented
caller, so leaf sample counts are not native self-time. Candidate call paths
must be validated with repeated throughput measurements. This is an Elisa
renderer change, not a new native-unwinding backend.

Validation: live text/HTML, saved nonempty text/HTML, and saved zero-sample
text/HTML all contain the notice (`build/sampling-attribution-*`). The empty
capture has zero samples; its `hello` workload intentionally returns 42, which
was checked explicitly. Native and sampling regressions passed (exit 0;
`build/sampling-attribution-native-regression.log` and
`build/sampling-attribution-sampling-regression.log`).

To corroborate instrumented callback stacks, macOS `/usr/bin/sample` observed
the uninstrumented self-hosted compiler at `200de8b0` compiling its own driver
to a native object with `-O0`. The sampler requested a 40-second window at a
2-millisecond interval, using `-mayDie -fullPaths`. Both sampler and compiler
returned exit 0. Evidence: `build/native-stack-compiler-sample.txt`,
`build/native-stack-sampler.log`, and `build/native-stack-profile-workload.log`.
The source/runtime were not modified during capture. This external tool is a
diagnostic cross-check, not an implemented Elisa-profiler collection mode.

The main-thread call graph contains 17,029 sampled stacks. In the report's
collapsed top-of-stack section, `string_views_eq` has 3,216 observations and
`ctx_string_views_eq` 1,365 (combined 26.9%); `_platform_memcmp` has only 153
(0.9%). `arena_take_free_block` has 1,615 (9.5%),
`ctx_aos_store_record` 399, `Backend.disjoint_scan_expr` 317,
`Semantic.positional_construction_expression` 280,
`arena_reclaim_allocation` 277, and `arena_take_free_block_chain` 271.
These are observed native top-frame counts, not instrumented function counts
or proof of a CPU-time percentage, and this single sampled run is not a
performance comparison.

This shifts the next investigation toward string-comparison call overhead
and free-block probing. Inspection confirms string equality already checks
length and pointer identity before `memcmp`, while ordinary generated sview
comparisons unconditionally call `ctx_string_views_eq`, which calls
`string_views_eq`. The runtime object is intentionally built at `-O0` to avoid
whole-module removal of helpers required by later links. Candidate fast paths
must preserve operand evaluation, empty views, pointer identity, inequality,
and target ABI behavior; changing optimization levels alone is not validated.

## Experimental generated sview fast paths

Following the native-stack evidence, an unpromoted backend candidate emits
length/empty/pointer checks before calling the existing string comparator.
Both operands are evaluated once and a function-entry result slot avoids
per-iteration stack growth. The initial version crashed during self-compilation
when a legacy operand was not an LLVM view aggregate. A canonical LLVM-type
guard retains the existing runtime call for those representations. That
representation mismatch still warrants a focused investigation; the guard
does not prove all legacy lowering paths correct.

The guarded candidate self-built successfully. Baseline and candidate both
passed `test/repro/sview_equality_fastpath.elisa`, covering unequal lengths,
distinct equal views, empty views, inequality, loop comparisons, and once-only
left-to-right operand evaluation. The simple initial reproducer's emitted IR
also passed LLVM verification. Broad code-generation regression validation and
promotion gates have **not** yet run; this candidate is not the installed compiler.

Sequential native-object baseline/candidate/candidate/baseline wall times were
38.74/37.62/36.95/38.00s (means 38.370s and 37.285s, 2.83% observed reduction).
Peak RSS increased from approximately 1.194 GB to 1.255 GB (~5.1%); retired
instructions increased from 631.846 to 647.313 billion (~2.4%). The candidate
was rebuilt with its own code generation before timing. Each compiler's two
objects matched; cross-compiler objects intentionally differ. These two pairs
show a tradeoff, not an established general improvement. Compare a smaller
length-only fast path and validate behavior before promotion.

Evidence in the compiler worktree:
`build/sview-fastpath-{baseline,candidate}-{a,b}.log`,
`build/sview-fastpath-test-{baseline,candidate}.log`, and
`build/sview-fastpath-debug-backtrace.log`.

## Length-only sview equality fast path (2026-09-09)

Compiler `2d44a99e` selects a smaller variant of the preceding experiment:
unequal-length canonical views return false locally; all equal-length views
use the existing comparator. Noncanonical lowered operands retain the legacy
call. Both expressions are evaluated before the branch, and the temporary
result resides in the function entry block. This supersedes the unpromoted
length/empty/pointer candidate above.

After rebuilding the candidate with its own code generation, native-object
baseline/candidate/candidate/baseline timings were 37.96/35.88/35.72/38.05s.
Means were 38.005s and 35.800s (5.80% observed reduction). Retired instructions
fell from 631.691 to 564.025 billion (10.71%). Mean peak RSS increased from
1.193 GB to 1.219 GB (2.18%). Each compiler emitted identical objects across
its two runs; cross-compiler byte identity is intentionally not expected.
Two pairs are preliminary timing evidence, not a portable speed guarantee.
Compiler-worktree logs: `build/sview-length-{baseline,candidate}-{a,b}.log`.

Validation completed before promotion:

- All 560 fixture/breadth exit statuses and diagnostics matched baseline;
  all 320 successful candidate LLVM outputs passed verification, with no
  existing-invalid outputs (`build/.sview-length-validation.NureZm`, exit 0).
- Executable differential tests produced identical reports: 88 agreed with
  stage0, and the same existing `with_block` compilation divergence on both
  baseline and candidate. Both suites exited 1; their complete reports matched.
  This is no-new-divergence evidence, not an all-green differential suite.
  Logs: `build/sview-length-differential-{baseline,candidate}.log`.
- The focused executable regression passed, including an additional check
  that an unequal-length comparison evaluates both operands once in order
  (`build/sview-length-test.log`).

Promotion checks passed with captured exit 0: fresh seed/manifest and all 11
local branch tips included; self-host stages A (5/5), B (19,776,736 bytes), C
(byte-identical fixed point), D (40 repeat objects); profiler rebuild; native
and sampling regressions. Profiler-worktree logs:
`build/sview-length-committed-{seed,self-host,profiler-build,native-regression,sampling-regression}.log`.

## Bounded mmap region cache and keyed reclaim hint (2026-09-09)

The compiler worktree commits `4702bcf9` and `13c62cc0` keep up to 128 recently freed, small
mmap-backed regions in an intrusive cache instead of retaining only one region
or calling `munmap` immediately. The cache reuses regions by capacity and resets
their headers before publication. Reclaimed darray spans also use a separate
arena-address-keyed hint, so bump-only arenas skip the stale process-wide
free-span walk. Lifecycle handling clears or migrates the hint across reset,
rewind, trim, free, and adopt. The public `Arena` layout and stage0 interface
remain unchanged.

Fresh products were seeded at `-O0` from the current compiler source, with the
baseline product retaining the prior 16-entry cache. Six alternating native-object
builds of `src/driver/elisac.elisa` measured:

| product | mean wall | mean user | mean system | max RSS |
| --- | ---: | ---: | ---: | ---: |
| baseline (16 entries) | 20.615 s | 16.637 s | 3.935 s | 1,142,560 KB |
| candidate (128 entries) | 19.170 s | 16.660 s | 2.390 s | 1,189,056 KB |

That is a 7.01% wall-time throughput improvement, a 39.26% reduction in system
time, effectively neutral user time (+0.14%), and a 4.07% peak-RSS increase on
this workload. All 12 emitted objects were byte-identical. A 256-entry candidate
was rejected after measuring 1.02% slower wall time and 0.29% slower user time.
The focused allocator fixtures and self-host stages A–D passed; stage C reached
a byte-identical fixed point and stage D was deterministic across 10 runs. The
full optimization pipeline passed 139 fixtures at `-O0`, `-O2`, and `-O3`.
Evidence is in the compiler worktree under
`build/cache64-bench-*.time`, `build/cache128-bench-*.time`,
`build/cache256-bench-*.time`, and `build/arena-cache-hint-self-host-gen2/`.

## Context string equality bridge and branch prediction hint (2026-09-09)

Compiler commit `cb333aec` removes the nested `ctx_string_views_eq` to
`string_views_eq` call by keeping the proven fast path directly in the context
runtime wrapper. It also marks the measured unequal-length exit as
`if likely lhs.len != rhs.len:` in both string-equality implementations. The
Elisa branch hint lowers to LLVM branch weights and does not alter semantics.

Fresh `-O0` products were compared with six alternating native-object builds of
`src/driver/elisac.elisa`:

| product | mean wall | mean user | mean system | max RSS |
| --- | ---: | ---: | ---: | ---: |
| direct bridge, no hint | 20.793 s | 17.350 s | 3.367 s | 1,142,320 KB |
| direct bridge + length hint | 20.113 s | 16.570 s | 3.397 s | 1,142,352 KB |

The hint candidate reduced wall time by 3.27% and user time by 4.50% with
effectively unchanged RSS. The corresponding `-O2` stage1-product check was
13.318 s versus 13.100 s wall time (1.64% lower), with identical emitted-object
hashes in all 12 comparisons. The direct bridge itself had already reduced the
same compile benchmark from 22.955 s to 21.227 s wall time and from 19.072 s to
17.415 s user time. Self-host stages A–D, the 139-fixture optimization
pipeline, native regression, and sampling regression all passed after
promotion.

An additional `while likely` hint on the bounded arena free-list probe was
rejected: six runs changed user time by only 0.22%, within run noise. The
allocator source remains unhinted. Evidence is in the compiler worktree under
`build/string-branch-bench-*.time`, `build/string-branch-o2-bench-*.time`, and
`build/arena-loop-bench-*.time`.

## Cold arena cache admission hint (2026-09-09)

Compiler commit `4e182d8e` marks the bounded mmap-cache admission test in
`free_region` as `if unlikely`. Once the 128-entry cache is warm, teardown
usually takes the direct unmap path, so this keeps that steady-state path as
the fall-through branch. This is a code-layout hint only; cache capacity,
ownership, and zeroing semantics are unchanged.

Twelve alternating runs of the current 128-entry control product and the
hinted product compiled `src/driver/elisac.elisa` to native objects at `-O0`:

| product | mean wall | mean user | mean system | max RSS |
| --- | ---: | ---: | ---: | ---: |
| control | 20.741 s | 16.848 s | 3.786 s | 1,191,744 KB |
| `if unlikely` | 20.253 s | 16.918 s | 3.211 s | 1,189,456 KB |

The hint reduced wall time by 2.35% and system time by 15.19%, while user time
was effectively neutral (+0.42%) and peak RSS did not increase. All 24 output
objects were byte-identical. A complementary `if likely` on the cache-hit
condition was rejected: six alternating runs were 5.36% slower wall time and
had 44.2% higher system time. The hinted compiler passed self-host stages A–D
and retained the byte-identical fixed point and 10-repeat determinism.
Evidence is in the compiler worktree under
`build/branch-hint-bench.7jf0nF/` and `build/branch-hint-combined-bench.BinYts/`.

## Optimized stage1 compiler product (2026-09-09)

The compiler seed script already supports optimized products, but the profiler
Makefile initially requested `-O0`, so normal reseeding built a slower compiler
than the compiler worktree's default. The first promotion selected `-O2`; the
follow-up comparison below selects `-O3` for the stage1 seed. This changes only
the optimization level of the compiler executable;
the compiler source and emitted target optimization flags remain independent.

Six alternating runs of stage1 products built from compiler commit `4e182d8e`
compiled `src/driver/elisac.elisa` to a native object at `-O0`:

| stage1 product | mean wall | mean user | mean system | max RSS |
| --- | ---: | ---: | ---: | ---: |
| `-O0` | 20.060 s | 17.025 s | 2.900 s | 1,189,360 KB |
| `-O2` | 12.813 s | 9.917 s | 2.800 s | 1,186,976 KB |

The O2 product reduced wall time by 36.13% and user time by 41.78%, with
effectively unchanged system time and 0.20% lower peak RSS. All 12 emitted
objects were byte-identical. Self-host stages A–D, the 139-fixture optimization
pipeline, compiler-manifest freshness, native regression, and sampling smoke
all pass with the O2 product. Evidence is in the compiler worktree under
`build/stage1-opt-level-bench.XvYzDM/`.

The follow-up O3 comparison used twelve alternating runs per product from the
same compiler source (24 total), again compiling the target at `-O0`:

| stage1 product | mean wall | mean user | mean system | max RSS |
| --- | ---: | ---: | ---: | ---: |
| `-O2` | 12.999 s | 9.841 s | 3.098 s | 1,187,536 KB |
| `-O3` | 12.748 s | 9.799 s | 2.888 s | 1,187,536 KB |

O3 is therefore the selected default: it reduced wall time by a further 1.93%,
user time by 0.43%, and system time by 6.78%, with unchanged peak RSS and
byte-identical objects. Evidence is in the compiler worktree under
`build/stage1-o3-bench.KQQ9hl/`.

## Compiler branch reconciliation and full gate (2026-09-09)

The dedicated compiler worktree at
`../elisa-compiler-worktrees/profiler` was refreshed against the owner
worktree at `../Elisa-compiler` before the final gate. The owner `work` branch
is clean at `7890e0f3` (`Improve parser diagnostics and named errors`), and
that tip is an ancestor of the dedicated `codex/profiler` branch at
`df6cf817`. The dedicated branch also contains the profiler-loop compiler
changes `cb333aec`, `13c62cc0`, `4e182d8e`, and `eb63abb1`.

The installed global tools under `~/.elisac` are not the active compiler: its
`stage1/SNAPSHOT` identifies revision `3c8924aa` from 2026-09-04, and its
stage1/runtime artifacts were copied on 2026-09-05. They predate the dedicated
worktree's current fixes and O3 product. `Makefile` now prefers the checked-out
stage0 sibling explicitly (with `STAGE0_BIN`/`ELISACORE_BIN` still available
as deliberate overrides), while all stage1 compilation uses the dedicated
`COMPILER_WORKTREE`.

The all-branch audit initially identified three local branch tips that were
not represented by the dedicated branch history:
`ce8bd633` (`codex/structpy-tree`), `81c74901`
(`codex/transpiler-local-stage1`), and `1b3d05bf` (`nw-port`). Inspection
showed that the later modular parser/backend implementation already contained
the equivalent source functionality from the first two tips. The stable
scratch-root safeguard from the third tip was ported into
`test/parity/scope_binding_smoke.sh`. Merge-history entries now record all
three tips (`0782fd06`, `fb7ceb9d`, and `df6cf817`), preserving branch
provenance without regressing the newer modular source layout. A stale removed
temporary worktree was also pruned after confirming it was no longer a live
checkout.

The final audit reports 11/11 local branch tips included and 13 live
worktrees. The O3 stage1 product and manifest were reseeded from the dedicated
compiler after reconciliation. The complete profiler `make test` gate then
passed with exit 0, including the compiler manifest and identity checks,
self-hosting stages A–D (byte-identical fixed point and 40 repeat objects),
the 139-fixture optimization pipeline at `-O0`, `-O2`, and `-O3`, native and
sampling regressions, collector/schema/protocol/property checks, runtime ABI,
timing-failure checks, bootstrap/path/process-group cleanup, and the remaining
profiler workload and artifact suites. The dedicated compiler and profiler
source worktrees are clean after the gate.

## Fresh O3 native-stack cross-check (2026-09-09)

After reconciliation, the active O3 stage1 product compiled its own driver to
a native object successfully in 13.9 seconds. A concurrent macOS
`/usr/bin/sample` capture collected 5,937 main-thread stack observations. The
largest visible groups were LLVM target object emission (1,326 observations
through `LLVMTargetMachineEmitToFile`) and `__munmap` (1,501 observations).
The O3 product is dead-stripped and carries no local Elisa function symbols,
so the remaining stage1 frames are reported as load-address offsets rather
than actionable function names. This is useful confirmation of the broad
LLVM/allocator split, but it is not evidence for another `likely`/`unlikely`
source hint. The accepted hints remain the measured string-length mismatch
fast path and cold arena-cache admission; further hints require symbolized or
instrumented attribution plus repeated end-to-end throughput measurements.

## Refreshed compiler sampling checkpoint (2026-09-10)

The dedicated compiler was fast-forwarded to main `b34733a1` and rebuilt at
O3. Its content, artifact, toolchain, ABI, and flag manifest checks passed.
While this binary compiled its own driver during self-host validation, a
two-second native sample retained 1,437 main-thread observations, including
529 in `__munmap` (36.8% of this window). The capture is
`build/selfhost-refresh-stack-20260910.txt` in the profiler checkout.

This is a partial-window attribution observation, not a whole-compilation
percentage or a throughput improvement. Other compiler and WASM builds were
active, and local Elisa frames remain unnamed offsets. The current region
cache permits 128 entries; cache misses and regions exceeding the cacheable
size are investigation targets, not yet proven explanations for the unmaps.
Self-host validation was still running when this checkpoint was recorded.

## Promote a local baseline

### Rejected expansion to string selection paths

Applying the same length guard to four membership/pattern-matching emitter
paths showed no throughput gain. Sequential baseline/candidate/candidate/baseline
native-object times were 35.71/35.88/35.74/35.63s (means 35.670s and 35.810s).
Retired instructions decreased slightly (564.136 to 562.903 billion), but that
proxy did not translate into throughput. Each compiler's repeated objects
matched. The candidate self-built and both compilers passed the new executable
selection regression. The source expansion was reverted; regression coverage
was retained in compiler commit `09269473`.

Compiler-worktree evidence: `build/sview-shared-{baseline,candidate}-{a,b}.log`
and `build/sview-selection-{baseline,candidate}.log`. Source was restored exactly
and seed/manifest refreshed (`build/sview-shared-restored-seed.log` in the profiler
worktree). The retained binary-equality optimization is unchanged.

Keep release or reference history separate from the build cache with an
explicit promotion:

```sh
bin/elisa-profiler baseline promote capture.json \
  --store .elisa-profiler/baselines \
  --name release-1 \
  --reason "validated reference workload"
```

Promotion accepts only a schema-valid successful complete capture. It writes
the original capture as `release-1.elisaprof` and an adjacent
`release-1.json` audit record containing source/compiler/mode identity, the
capture digest, and the human reason. Names are restricted to portable
basename characters and existing names are refused; replace-by-default is
deliberately unavailable so history cannot be rewritten accidentally. Compare
the stored `.elisaprof` path explicitly when selecting a baseline.
