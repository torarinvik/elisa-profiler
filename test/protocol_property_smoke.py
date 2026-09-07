#!/usr/bin/env python3
"""Exercise framed protocol recovery invariants and forward-compatible records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "examples" / "hello.elisa"

PROTOCOL_VERSION = 1
PROTOCOL_PREFIX = f"ELISA_PROFILE\t{PROTOCOL_VERSION}\t".encode()
FRAME_FNV_OFFSET = 14695981039346656037
FRAME_FNV_PRIME = 1099511628211
MAX_U64 = (1 << 64) - 1
MAX_PROTOCOL_FRAME_BYTES = 1024 * 1024
READ_CHUNK_BYTES = 8192
META_FIELD_COUNT = 16
CAPTURE_MARKER = 1
INITIAL_FRAME_SEQUENCE = 0
FRAME_TERMINATOR = b"\n"
INVALID_CHECKSUM_MASK = 1
TRUNCATED_DECLARED_LENGTH = 999
EXTENSION_PAYLOAD_BYTES = READ_CHUNK_BYTES + 257


def frame_checksum(payload: bytes) -> int:
    checksum = FRAME_FNV_OFFSET
    for byte in payload:
        checksum = ((checksum ^ byte) * FRAME_FNV_PRIME) & MAX_U64
    return checksum


def frame(
    sequence: int,
    payload: bytes,
    *,
    declared_length: int | None = None,
    checksum: int | None = None,
    terminated: bool = True,
) -> bytes:
    length = len(payload) if declared_length is None else declared_length
    digest = frame_checksum(payload) if checksum is None else checksum
    header = f"ELISA_PROFILE\t{PROTOCOL_VERSION}\tframe\t{sequence}\t{length}\t{digest}\t".encode()
    return header + payload + (FRAME_TERMINATOR if terminated else b"")


def protocol_record(kind: str, *fields: object) -> bytes:
    values = "\t".join([kind, *(str(field) for field in fields)])
    return PROTOCOL_PREFIX + values.encode()


def valid_capture(include_extension: bool = False) -> bytes:
    begin = protocol_record("begin", CAPTURE_MARKER)
    metadata = protocol_record("meta", *([0] * META_FIELD_COUNT))
    records = [frame(INITIAL_FRAME_SEQUENCE, begin)]
    next_sequence = INITIAL_FRAME_SEQUENCE + 1
    if include_extension:
        extension = (
            protocol_record("extension", "future_metric")
            + b"\t"
            + b"x" * EXTENSION_PAYLOAD_BYTES
        )
        records.append(frame(next_sequence, extension))
        next_sequence += 1
    records.append(frame(next_sequence, metadata))
    return b"".join(records)


def split_at_read_boundaries(data: bytes) -> list[bytes]:
    """Write a capture in chunks that cross the native file-read boundary."""
    cut_points = [
        1,
        31,
        READ_CHUNK_BYTES - 1,
        READ_CHUNK_BYTES,
        READ_CHUNK_BYTES + 1,
        len(data) - 1,
    ]
    points = sorted({point for point in cut_points if 0 < point < len(data)})
    chunks: list[bytes] = []
    start = 0
    for stop in points + [len(data)]:
        chunks.append(data[start:stop])
        start = stop
    return chunks


def write_manifest(work: Path, capture: bytes, chunks: list[bytes]) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    capture_path = work / "capture.bin"
    with capture_path.open("wb") as stream:
        for chunk in chunks:
            stream.write(chunk)
    manifest_path = work / "capture.manifest.json"
    manifest = {
        "kind": "elisa_profile_capture_manifest",
        "schema_version": 1,
        "state": "partial",
        "source": str(SOURCE),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "collection_mode": "full",
        "capture_path": str(capture_path),
        "requested_repetitions": 1,
        "completed_repetitions": 1,
        "successful_repetitions": 0,
        "failed_repetitions": 1,
        "events": 0,
        "capture_started": True,
        "capture_complete": False,
        "frame_dropped": 0,
        "capture_index": {
            "format": "record-framed-v1",
            "bytes": len(capture),
            "valid_frames": 0,
            "valid_bytes": 0,
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def recover(native: Path, work: Path, capture: bytes, chunks: list[bytes] | None = None) -> tuple[subprocess.CompletedProcess[bytes], dict | None]:
    manifest = write_manifest(work, capture, chunks or [capture])
    output = work / "report.json"
    process = subprocess.run(
        [str(native), "recover", str(manifest), "--format", "json", "--output", str(output)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return process, json.loads(output.read_text(encoding="utf-8")) if output.exists() else None


def report_projection(report: dict) -> dict:
    summary = dict(report["summary"])
    summary.pop("valid_frames", None)
    summary.pop("valid_capture_bytes", None)
    return {
        "summary": summary,
        "locations": report["locations"],
        "functions": report["functions"],
        "call_edges": report["call_edges"],
        "stacks": report["stacks"],
        "samples": report["samples"],
        "thread_loss": report["thread_loss"],
    }


def expect_rejected(native: Path, work: Path, capture: bytes, label: str) -> None:
    process, report = recover(native, work, capture)
    assert process.returncode != 0, f"{label} was accepted"
    assert report is None, f"{label} unexpectedly emitted a report"
    assert b"malformed native protocol" in process.stderr, (label, process.stderr)


def main() -> int:
    native = Path(sys.argv[1]) if len(sys.argv) == 2 else ROOT / "bin" / "elisa-profiler"
    with tempfile.TemporaryDirectory(prefix="elisa-profiler-protocol-property-") as directory:
        work = Path(directory)

        baseline_capture = valid_capture()
        baseline_process, baseline_report = recover(native, work / "baseline", baseline_capture)
        assert baseline_process.returncode == 0, baseline_process.stderr
        assert baseline_report is not None

        extension_capture = valid_capture(include_extension=True)
        extension_process, extension_report = recover(
            native,
            work / "extension",
            extension_capture,
            split_at_read_boundaries(extension_capture),
        )
        assert extension_process.returncode == 0, extension_process.stderr
        assert extension_report is not None
        assert report_projection(extension_report) == report_projection(baseline_report)
        assert extension_report["summary"]["valid_frames"] == baseline_report["summary"]["valid_frames"] + 1
        assert extension_report["summary"]["valid_capture_bytes"] == len(extension_capture)

        truncated_payload = protocol_record("meta")
        truncated_capture = baseline_capture + (
            PROTOCOL_PREFIX
            + f"frame\t2\t{TRUNCATED_DECLARED_LENGTH}\t0\t".encode()
            + truncated_payload
        )
        truncated_process, truncated_report = recover(native, work / "truncated", truncated_capture)
        assert truncated_process.returncode == 0, truncated_process.stderr
        assert truncated_report is not None
        assert truncated_report["recovery"]["tail_truncated"] is True
        assert truncated_report["recovery"]["valid_frames"] == baseline_report["summary"]["valid_frames"]
        assert truncated_report["recovery"]["valid_bytes"] == len(baseline_capture)
        assert truncated_report["recovery"]["capture_bytes"] == len(truncated_capture)

        complete_end = protocol_record("end", CAPTURE_MARKER)
        invalid_checksum = frame(
            2,
            complete_end,
            checksum=frame_checksum(complete_end) ^ INVALID_CHECKSUM_MASK,
            terminated=False,
        )
        expect_rejected(native, work / "checksum", baseline_capture + invalid_checksum, "complete bad checksum")

        invalid_length = frame(
            2,
            complete_end,
            declared_length=len(complete_end) - 1,
            terminated=False,
        )
        expect_rejected(native, work / "length", baseline_capture + invalid_length, "undersized declared length")

        oversized_length = frame(
            2,
            complete_end,
            declared_length=MAX_PROTOCOL_FRAME_BYTES + 1,
            terminated=False,
        )
        expect_rejected(native, work / "oversized", baseline_capture + oversized_length, "oversized declared length")

        sequence_gap = frame(3, complete_end, terminated=False)
        expect_rejected(native, work / "sequence", baseline_capture + sequence_gap, "frame sequence gap")

    print("protocol property smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
