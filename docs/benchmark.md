# Native benchmark manifests

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
Committed-compiler bootstrap and profiler regressions remain pending.

## Broad regression checkpoint (2026-09-09)

After compiler `2ec59777`, the full `make test` log reached its final
`process-group cleanup OK` check, and the observed make process exited.
The log includes successful bootstrap fixed-point/repeat checks, native and
sampling regressions, cache and identity checks, protocol/property tests,
collector sanitizer checks, recovery, budgets, and process cleanup.
No failure is reported in `build/post-optimizations-full-test.log`.
The original process exit-status handle was not recovered, so this records
the completed test-log evidence rather than an independently captured exit code.

## Promote a local baseline

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
