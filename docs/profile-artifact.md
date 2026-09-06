# Elisa profile artifacts

`elisa-profiler record SOURCE --format json --artifact-output capture.elisaprof`
emits a deterministic JSON v1 artifact envelope around the native v2 profile report. The
envelope is deliberately readable and uncompressed in this first container
slice, so it can be inspected or recovered with ordinary JSON tooling.

The top-level contract is:

```json
{
  "artifact_version": 1,
  "kind": "elisa-profile",
  "manifest": {
    "capture_format": "profile-json-v2",
    "compression": "none",
    "capture_bytes": 1234
  },
  "capture": {
    "schema_version": 2,
    "envelope": {
      "major": 2,
      "minor": 0,
      "kind": "profile",
      "compatibility": "backward-compatible-v1"
    }
  }
}
```

`capture_bytes` is the byte count of the embedded profile JSON as written by
the native renderer. The embedded capture is a complete v2 profile and
is validated with `docs/profile.schema.json`. `report` unwraps the envelope
before rendering JSON, text, folded stacks, Speedscope, or HTML. `compare`
accepts raw v1 reports for migration and comparison, as well as these v2
envelopes. The native readers accept the legacy v1 shape without an envelope,
while v2 requires the envelope's major/minor compatibility fields.

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
still has no compression; compression and chunked storage remain planned
extensions. The sidecar manifest carries a durable framed capture index, and
the native `recover` command reconstructs a bounded report from a partial
manifest/capture. Raw JSON reports can opt in to an exact source snapshot with
`--embed-source`; the top-level `source_snapshot` contains the UTF-8 source
bytes and their SHA-256 digest. Snapshots are intentionally optional because
they increase report size.
The quality object inside the embedded capture is authoritative about target
termination and bounded-detail loss.

When `--cache-dir PATH` is supplied, the native profiler uses a content-addressed
instrumented executable cache. The report's `build_cache` object records the
validated key, `miss`/`hit`/`bypass` status, and a human-readable explanation.
Each entry is an atomically published executable plus JSON metadata describing
the source dependency digest, compiler provenance, runtime and collector
digests, tool identities, optimization level, host, and fixed link flags.
Cache lookup is conservative: missing, malformed, permission-invalid, or
unavailable entries are rebuilt, and a dependency change produces a new key.
The cache is opt-in; `--no-cache` makes that policy explicit.

If a `running`, `finalizing`, or `partial` manifest remains beside a capture,
`elisa-profiler recover MANIFEST --format json` reconstructs a v2 report from
the checksum-validated framed records. Recovery verifies the source digest and
stops before an incomplete trailing frame. The result is marked
`quality.capture = recovered`, includes a `recovery` object with the manifest,
capture, and validated-boundary metadata, and never invents target exit or
elapsed-time values. A missing capture or changed source is an actionable
failure rather than a guessed report.
