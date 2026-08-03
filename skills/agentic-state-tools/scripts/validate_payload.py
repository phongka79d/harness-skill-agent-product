"""Validate a JSON payload against the small JSON Schema subset used here."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from runtime_utils import read_json, read_payload


TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def _resolve_local_reference(root_schema: dict[str, Any], reference: str) -> dict[str, Any]:
    if reference == "#":
        return root_schema
    if not reference.startswith("#/"):
        raise ValueError(f"unsupported local schema reference: {reference}")
    current: Any = root_schema
    for token in reference[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or token not in current:
            raise ValueError(f"local schema reference does not exist: {reference}")
        current = current[token]
    if not isinstance(current, dict):
        raise ValueError(f"local schema reference must resolve to an object: {reference}")
    return current


def validate(
    value: Any,
    schema: dict[str, Any],
    path: str = "$",
    *,
    base_path: Path | None = None,
    root_schema: dict[str, Any] | None = None,
) -> list[str]:
    if root_schema is None:
        root_schema = schema
    reference = schema.get("$ref")
    if isinstance(reference, str) and reference:
        if reference.startswith("#"):
            try:
                referenced = _resolve_local_reference(root_schema, reference)
            except ValueError as exc:
                return [f"{path}: {exc}"]
            return validate(value, referenced, path, base_path=base_path, root_schema=root_schema)
        if base_path is None:
            return [f"{path}: schema reference cannot be resolved without a base path: {reference}"]
        target = (base_path / reference).resolve()
        try:
            referenced = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return [f"{path}: unable to load schema reference {reference}: {exc}"]
        if not isinstance(referenced, dict):
            return [f"{path}: referenced schema must be an object"]
        return validate(value, referenced, path, base_path=target.parent, root_schema=referenced)
    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: value does not match const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value is not in enum {schema['enum']}")
    if "oneOf" in schema:
        branches = schema["oneOf"]
        if not isinstance(branches, list) or not branches:
            errors.append(f"{path}: oneOf must contain at least one schema")
        else:
            valid_branches = 0
            for branch in branches:
                if isinstance(branch, dict) and not validate(
                    value,
                    branch,
                    path,
                    base_path=base_path,
                    root_schema=root_schema,
                ):
                    valid_branches += 1
            if valid_branches != 1:
                errors.append(f"{path}: oneOf matched {valid_branches} schemas; exactly one is required")
    expected = schema.get("type")
    if expected:
        expected_types = expected if isinstance(expected, list) else [expected]
        matches = False
        for expected_name in expected_types:
            expected_type = TYPE_MAP.get(expected_name)
            if expected_type is None:
                errors.append(f"{path}: unsupported schema type {expected_name}")
                continue
            if isinstance(value, expected_type) and not (expected_name in {"integer", "number"} and isinstance(value, bool)):
                matches = True
                break
        if not matches:
            return [f"{path}: expected one of {expected_types}"]
    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            errors.append(f"{path}: string is shorter than minLength")
        if schema.get("pattern") and not re.search(schema["pattern"], value):
            errors.append(f"{path}: string does not match pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: number is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: number is above maximum")
    if isinstance(value, dict):
        for required in schema.get("required", []):
            if required not in value:
                errors.append(f"{path}.{required}: required field is missing")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        unknown = set(value) - set(properties)
        if additional is False:
            errors.extend(f"{path}.{key}: additional property is not allowed" for key in sorted(unknown))
        elif isinstance(additional, dict):
            for key in sorted(unknown):
                errors.extend(
                    validate(
                        value[key],
                        additional,
                        f"{path}.{key}",
                        base_path=base_path,
                        root_schema=root_schema,
                    )
                )
        for key, child in properties.items():
            if key in value:
                errors.extend(
                    validate(
                        value[key],
                        child,
                        f"{path}.{key}",
                        base_path=base_path,
                        root_schema=root_schema,
                    )
                )
    if isinstance(value, list):
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            errors.append(f"{path}: array has fewer than minItems")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            errors.append(f"{path}: array has more than maxItems")
        if schema.get("uniqueItems") is True:
            serialized = [json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for item in value]
            if len(serialized) != len(set(serialized)):
                errors.append(f"{path}: array items must be unique")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            errors.extend(
                validate(
                    item,
                    schema["items"],
                    f"{path}[{index}]",
                    base_path=base_path,
                    root_schema=root_schema,
                )
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--schema", required=True)
    args = parser.parse_args()
    try:
        payload = read_payload(args.input)
        schema = read_json(args.schema)
        errors = validate(payload, schema, base_path=Path(args.schema).resolve().parent)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(f"INVALID: {error}", file=sys.stderr)
        return 1
    print("VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
