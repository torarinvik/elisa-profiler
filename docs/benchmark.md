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
