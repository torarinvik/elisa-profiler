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
