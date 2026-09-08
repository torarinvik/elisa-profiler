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
    "capture_bytes": 1234,
    "max_artifact_bytes": 134217728
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
the native renderer. `max_artifact_bytes` records the output budget selected
for the invocation; the artifact is rejected before publication when its
serialized bytes would exceed that budget. The embedded capture is a complete
v2 profile and
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

Use `--max-artifact-bytes BYTES` to lower the artifact budget for a constrained
run. The default is 128 MiB. A rejected artifact is never atomically published;
the capture manifest remains available for recovery and diagnosis.

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

The framed transport reserves `ELISA_PROFILE\t1\textension\tNAME\t...` for
forward-compatible optional records. Older decoders still verify the frame's
sequence, declared length, and checksum, then ignore the extension payload so
new metadata cannot silently corrupt the evidence they do understand. Recovery
only treats an unterminated final frame as a recoverable tail when its header
or declared payload is genuinely incomplete; a complete frame with a bad
checksum or inconsistent length is rejected as malformed.

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

An existing instrumented executable can be reused with
`profile SOURCE --prebuilt /absolute/path/to/program`. The source argument is
still required so dependency and source identities remain explicit. The native
validator requires an executable absolute path and checks its defined Elisa
entry and trace callback symbols with `llvm-nm`, including the callback family
needed by the selected collection mode. Reports record
`target.build_kind = prebuilt` and the supplied executable path; ordinary or
partially instrumented binaries are rejected before launch.

If a `running`, `finalizing`, or `partial` manifest remains beside a capture,
`elisa-profiler recover MANIFEST --format json` reconstructs a v2 report from
the checksum-validated framed records. Recovery verifies the source digest and
stops before an incomplete trailing frame. The result is marked
`quality.capture = recovered`, includes a `recovery` object with the manifest,
capture, and validated-boundary metadata, and never invents target exit or
elapsed-time values. A missing capture or changed source is an actionable
failure rather than a guessed report.
