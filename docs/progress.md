# Progress status

`profile` and `record` accept `--progress PATH`. When supplied, the native
Elisa executable atomically replaces that file at each major stage with one
JSON status object. The report stream is unaffected: JSON/text/folded/
Speedscope/HTML output remains the only data written to report stdout unless
`--output` is supplied.

The file follows [`progress.schema.json`](progress.schema.json). Status is a
snapshot, not an append-only event log; readers should poll it and treat the
last complete object as authoritative. A writer crash can leave the previous
valid snapshot in place because updates use the same atomic publication path
as reports and manifests.

States are emitted in this order when their work exists:

1. `compile_started`
2. `compile_complete`
3. `warmup_complete` once per warmup repetition
4. `capture_started` once per measured repetition
5. `repetition_complete` once per measured repetition
6. `rendering`
7. `complete`

`events`, `capture_bytes`, and `valid_frames` describe the most recently
normalized aggregate snapshot. They are evidence counters, not percentages.
`capture_complete` only becomes true when the normalized capture contains its
completion marker; a timeout or other partial capture remains explicitly
incomplete.
