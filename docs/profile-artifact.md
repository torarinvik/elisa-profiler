# Elisa profile artifacts

`elisa-profiler record SOURCE --format json --artifact-output capture.elisaprof`
emits a deterministic JSON v1 envelope around the native profile report. The
envelope is deliberately readable and uncompressed in this first container
slice, so it can be inspected or recovered with ordinary JSON tooling.

The top-level contract is:

```json
{
  "artifact_version": 1,
  "kind": "elisa-profile",
  "manifest": {
    "capture_format": "profile-json-v1",
    "compression": "none",
    "capture_bytes": 1234
  },
  "capture": { "schema_version": 1 }
}
```

`capture_bytes` is the byte count of the embedded profile JSON as written by
the native renderer. The embedded capture remains a complete v1 profile and
is validated with `docs/profile.schema.json`. `report` unwraps the envelope
before rendering JSON, text, folded stacks, Speedscope, or HTML. `compare`
also accepts either raw v1 reports or these envelopes.

This is a compatibility container, not yet the final recoverable stream
format. Chunk framing, checksums, progressive manifests, compression, source
snapshots, and durable partial-capture recovery remain planned M2/M3 work.
The quality object inside the embedded capture is authoritative about target
termination and bounded-detail loss.
