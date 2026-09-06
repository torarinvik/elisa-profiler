#!/usr/bin/env python3
"""Validate representative profiler reports with the checked-in JSON schema."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


class SchemaError(Exception):
    pass


def schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    raise SchemaError(f"unsupported schema type: {expected}")


def resolve_ref(root: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise SchemaError(f"unsupported schema reference: {reference}")
    value: Any = root
    for component in reference[2:].split("/"):
        value = value[component]
    return value


def validate(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str) -> None:
    if "$ref" in schema:
        validate(value, resolve_ref(root, schema["$ref"]), root, path)
        return
    if "const" in schema and value != schema["const"]:
        raise SchemaError(f"{path}: expected {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaError(f"{path}: value is outside enum")
    expected_types = schema.get("type")
    if expected_types is not None:
        if isinstance(expected_types, str):
            expected_types = [expected_types]
        if not any(schema_type_matches(value, expected) for expected in expected_types):
            raise SchemaError(f"{path}: expected {expected_types}, got {type(value).__name__}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaError(f"{path}: value is below minimum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise SchemaError(f"{path}: value is not above exclusive minimum")
    if isinstance(value, dict):
        for required in schema.get("required", []):
            if required not in value:
                raise SchemaError(f"{path}: missing required property {required!r}")
        if schema.get("additionalProperties") is False:
            known_properties = set(schema.get("properties", {}))
            unknown_properties = sorted(set(value) - known_properties)
            if unknown_properties:
                raise SchemaError(
                    f"{path}: unexpected properties {', '.join(repr(item) for item in unknown_properties)}"
                )
        for name, child_schema in schema.get("properties", {}).items():
            if name in value:
                validate(value[name], child_schema, root, f"{path}.{name}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise SchemaError(f"{path}: too few items")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                validate(item, item_schema, root, f"{path}[{index}]")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} SCHEMA REPORT [...]")
    schema_path = Path(argv[0])
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    for report_path in map(Path, argv[1:]):
        report = json.loads(report_path.read_text(encoding="utf-8"))
        try:
            validate(report, schema, schema, str(report_path))
        except SchemaError as error:
            raise SystemExit(str(error)) from error
    print("profile schema smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
