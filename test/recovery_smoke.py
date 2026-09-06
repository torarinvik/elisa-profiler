#!/usr/bin/env python3
"""Verify recovery stops at the last complete framed record."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "docs" / "profile.schema.json"
MAX_NATIVE_PROTOCOL_FRAME_BYTES = 1024 * 1024


def frame(sequence: int, payload: bytes, declared_length: int | None = None) -> bytes:
    checksum = 14695981039346656037
    for byte in payload:
        checksum = ((checksum ^ byte) * 1099511628211) & ((1 << 64) - 1)
    length = len(payload) if declared_length is None else declared_length
    header = f"ELISA_PROFILE\t1\tframe\t{sequence}\t{length}\t{checksum}\t".encode()
    return header + payload + b"\n"


def main() -> int:
    native = Path(sys.argv[1]) if len(sys.argv) == 2 else ROOT / "bin" / "elisa-profiler"
    source = ROOT / "examples" / "hello.elisa"
    source_bytes = source.read_bytes()
    meta = b"ELISA_PROFILE\t1\tmeta\t" + b"\t".join([b"0"] * 16)
    complete = frame(0, b"ELISA_PROFILE\t1\tbegin\t1") + frame(1, meta)
    truncated = b"ELISA_PROFILE\t1\tframe\t2\t999\t0\tELISA_PROFILE\t1\tmeta\t"

    with tempfile.TemporaryDirectory(prefix="elisa-profiler-recovery-") as directory:
        work = Path(directory)
        capture = work / "capture.txt"
        capture.write_bytes(complete + truncated)
        manifest = work / "capture.manifest.json"
        manifest_payload = {
            "kind": "elisa_profile_capture_manifest",
            "schema_version": 1,
            "state": "partial",
            "source": str(source),
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "collection_mode": "full",
            "capture_path": str(capture),
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
                "bytes": len(complete),
                "valid_frames": 2,
                "valid_bytes": len(complete),
            },
        }
        manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
        output = work / "recovered.json"
        process = subprocess.run(
            [str(native), "recover", str(manifest), "--format", "json", "--output", str(output)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert process.returncode == 0, (process.returncode, process.stdout, process.stderr)
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["run"]["outcome"] == "incomplete_artifact", payload
        assert payload["quality"]["capture"] == "recovered", payload
        assert "recovered_partial" in payload["quality"]["reasons"], payload
        assert payload["summary"]["capture_started"] is True, payload
        assert payload["summary"]["capture_complete"] is False, payload
        assert payload["recovery"]["tail_truncated"] is True, payload
        assert payload["recovery"]["valid_frames"] == 2, payload
        assert payload["recovery"]["valid_bytes"] == len(complete), payload
        assert payload["recovery"]["capture_bytes"] == len(complete + truncated), payload
        subprocess.run([sys.executable, str(ROOT / "test" / "profile_schema_smoke.py"), str(SCHEMA), str(output)], check=True)
        legacy_manifest = work / "legacy.manifest.json"
        legacy_payload = dict(manifest_payload)
        legacy_payload.pop("collection_mode")
        legacy_payload.pop("capture_index")
        legacy_manifest.write_text(json.dumps(legacy_payload), encoding="utf-8")
        legacy_output = work / "legacy-recovered.json"
        legacy_process = subprocess.run(
            [str(native), "recover", str(legacy_manifest), "--format", "json", "--output", str(legacy_output)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert legacy_process.returncode == 0, (legacy_process.returncode, legacy_process.stdout, legacy_process.stderr)
        assert json.loads(legacy_output.read_text(encoding="utf-8"))["run"]["collection_mode"] == "full"
        oversized_capture = work / "oversized-frame.txt"
        oversized_capture.write_bytes(
            complete
            + frame(2, b"ELISA_PROFILE\t1\tend\t1", MAX_NATIVE_PROTOCOL_FRAME_BYTES + 1)
            + frame(3, b"ELISA_PROFILE\t1\tend\t1")
        )
        oversized_manifest = work / "oversized-frame.manifest.json"
        oversized_payload = dict(manifest_payload)
        oversized_payload["capture_path"] = str(oversized_capture)
        oversized_manifest.write_text(json.dumps(oversized_payload), encoding="utf-8")
        oversized_process = subprocess.run(
            [str(native), "recover", str(oversized_manifest), "--format", "json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert oversized_process.returncode != 0, "recovery accepted an oversized framed payload"
    print("recovery smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
