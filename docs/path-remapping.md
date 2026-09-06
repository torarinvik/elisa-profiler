# Display path remapping

Use `--path-map FROM=TO` with `profile` or `record` to replace a source-path
prefix in report-facing fields:

```text
bin/elisa-profiler profile /workspace/project/examples/hot_loop.elisa \
    --path-map /workspace/project=PROJECT --format json
```

Mappings are repeatable, boundary-aware, and longest-prefix wins:
`/workspace/project` matches `/workspace/project/examples/...`, but not
`/workspace/project-old/...`; a more specific `/workspace/project/examples`
mapping takes precedence over the broader project mapping. Replacements are
applied to the top-level `source` and normalized location/event source fields,
so moved reports can use stable project-relative identities.

The capture manifest deliberately retains the raw source path and digest for
local recovery. This private provenance is not used as the shared report
display path, and recovery still refuses to use a source whose bytes changed.
Include-expanded source-tree remapping will be added alongside compiler-owned
source identities.
