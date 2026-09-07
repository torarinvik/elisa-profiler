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
captures are executed in deterministic baseline-then-candidate order and the
comparison output contains the per-repetition observations, workload identity,
quality state, and any requested gate. This is a paired configuration with a
shared workload definition; it is not a claim that scheduler noise has been
eliminated. Interleaved randomized execution remains a future optimization of
the runner, while exact native comparison and machine-readable gate outcomes
are already available.

Intermediate reports use `<output>.baseline.json` and
`<output>.candidate.json`. The native command refuses to reuse pre-existing
intermediate names and removes both reports and their progress manifests after
the comparison completes. A failed side is surfaced as a benchmark failure and
does not produce a misleading comparison.
