"""Dependency-free validator for the small JSON Schema subset used here."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}
SUPPORTED_SCHEMA_KEYWORDS = {
    "$schema",
    "type",
    "enum",
    "pattern",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "required",
    "properties",
    "additionalProperties",
    "items",
    "minItems",
    "maxItems",
    "uniqueItems",
}
UNSUPPORTED_SCHEMA_KEYWORDS = {
    "$id",
    "$ref",
    "$defs",
    "definitions",
    "title",
    "description",
    "default",
    "examples",
    "oneOf",
    "allOf",
    "anyOf",
    "not",
    "const",
    "format",
    "patternProperties",
    "dependentRequired",
    "contains",
    "if",
    "then",
    "else",
    "unevaluatedProperties",
    "minProperties",
    "maxProperties",
    "propertyNames",
    "additionalItems",
}


def _find_unsupported_keywords(value: Any, path: str = "$") -> list[str]:
    """Reject schema keywords outside the deliberately small supported subset."""
    if not isinstance(value, dict):
        return []
    found: list[str] = []
    for key in value:
        if key in UNSUPPORTED_SCHEMA_KEYWORDS or key not in SUPPORTED_SCHEMA_KEYWORDS:
            found.append(f"{path}.{key}")
    properties = value.get("properties")
    if isinstance(properties, dict):
        for name, child in properties.items():
            found.extend(_find_unsupported_keywords(child, f"{path}.properties.{name}"))
    additional = value.get("additionalProperties")
    if isinstance(additional, dict):
        found.extend(_find_unsupported_keywords(additional, f"{path}.additionalProperties"))
    items = value.get("items")
    if isinstance(items, dict):
        found.extend(_find_unsupported_keywords(items, f"{path}.items"))
    return found


def _matches_type(value: Any, name: str) -> bool:
    return isinstance(value, TYPE_MAP[name]) and not (
        name in {"integer", "number"} and isinstance(value, bool)
    )


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value is not allowed")

    expected = schema.get("type")
    if expected:
        names = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(value, name) for name in names):
            return [f"{path}: expected {names}"]

    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            errors.append(f"{path}: string is too short")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            errors.append(f"{path}: string is too long")
        pattern = schema.get("pattern")
        if pattern and re.fullmatch(str(pattern), value) is None:
            errors.append(f"{path}: string does not match required pattern")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: required")
        props = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        if additional is False:
            for key in sorted(set(value) - set(props)):
                errors.append(f"{path}.{key}: unknown field")
        for key, child in props.items():
            if key in value:
                errors.extend(validate(value[key], child, f"{path}.{key}"))
        if isinstance(additional, dict):
            for key in sorted(set(value) - set(props)):
                errors.extend(validate(value[key], additional, f"{path}.{key}"))

    if isinstance(value, list):
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            errors.append(f"{path}: too few items")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            errors.append(f"{path}: too many items")
        if schema.get("uniqueItems") is True:
            seen: set[str] = set()
            for item in value:
                marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if marker in seen:
                    errors.append(f"{path}: duplicate items are not allowed")
                    break
                seen.add(marker)
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(validate(item, schema["items"], f"{path}[{index}]"))

    return errors


def validate_file(value: Any, schema_path: str | Path, label: str) -> None:
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    unsupported = _find_unsupported_keywords(schema)
    if unsupported:
        raise ValueError(
            f"{label} uses unsupported JSON Schema keywords: "
            + ", ".join(unsupported)
        )
    errors = validate(value, schema)
    if errors:
        raise ValueError(f"{label} validation failed: " + "; ".join(errors))
