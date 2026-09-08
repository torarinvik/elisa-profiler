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
