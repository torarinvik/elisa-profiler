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

When `--artifact-output PATH` (or `--output PATH`) is used, the native command
also maintains `PATH.manifest.json` beside the requested output. It is an
atomic, human-readable progress record with `running`, `finalizing`,
`complete`, or `partial` state, source digest, repetition progress, and the
temporary collector path. It also records a durable `capture_index` with the
last validated framed-record boundary (`bytes`, `valid_bytes`, and
`valid_frames`). If the profiler is interrupted, the last manifest and any
still-present capture file identify the recoverable evidence without
pretending that an unfinished stream is complete.

This is a compatibility container, not yet the final durable artifact format.
The native collector transport is already record-framed: each streamed record
carries a strict sequence number, byte length, and FNV-1a-64 checksum, and the
Elisa decoder validates those fields before normalization. The JSON artifact
still has no compression or automatic partial-capture recovery reader; those
remain planned M2/M3 work. The sidecar manifest does carry a durable framed
capture index. Raw JSON reports can opt in to an exact source snapshot with
`--embed-source`; the top-level `source_snapshot` contains the UTF-8 source
bytes and their SHA-256 digest. Snapshots are intentionally optional because
they increase report size.
The quality object inside the embedded capture is authoritative about target
termination and bounded-detail loss.
