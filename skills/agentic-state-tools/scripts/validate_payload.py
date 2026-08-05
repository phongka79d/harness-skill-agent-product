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


# The writers in HSP-802 own these versions.  Older artifacts may omit the
# field or carry a lower version, but a writer always publishes the current
# version and records the legacy classification when it performs that
# compatibility projection.
CURRENT_ARTIFACT_SCHEMA_VERSIONS = {
    "context": 1,
    "handoff": 1,
    "review": 2,
    "task-state": 1,
}


def _artifact_key(artifact_type: str) -> str:
    if not isinstance(artifact_type, str) or not artifact_type.strip():
        raise ValueError("artifact_type must be a non-empty string")
    value = artifact_type.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if value.endswith(".schema.json"):
        value = value[:-12]
    return value


def current_artifact_schema_version(artifact_type: str, expected_version: int | None = None) -> int:
    """Return the supported version for an artifact family."""

    if expected_version is not None:
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1:
            raise ValueError("expected schema version must be a positive integer")
        return expected_version
    key = _artifact_key(artifact_type)
    try:
        return CURRENT_ARTIFACT_SCHEMA_VERSIONS[key]
    except KeyError as exc:
        raise ValueError(f"no current schema version is registered for {key}") from exc


def classify_artifact_version(
    value: Any,
    artifact_type: str,
    *,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Classify an artifact without mutating it.

    Missing and lower versions are readable legacy inputs.  A future version
    is rejected so a newer artifact cannot be silently interpreted by an older
    writer.
    """

    if not isinstance(value, dict):
        raise ValueError("artifact payload must be an object")
    key = _artifact_key(artifact_type)
    current = current_artifact_schema_version(key, expected_version)
    raw = value.get("schema_version")
    declared_legacy = value.get("legacy_migration") is True
    if value.get("legacy_migration") not in (None, False, True):
        raise ValueError(f"{key}.legacy_migration must be a boolean")
    if raw is None:
        if value.get("legacy_migration") is False:
            raise ValueError(f"{key} cannot mark an unversioned artifact as non-legacy")
        return {
            "artifact_type": key,
            "current_version": current,
            "source_version": None,
            "classification": "LEGACY_UNVERSIONED",
            "is_legacy": True,
        }
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ValueError(f"{key}.schema_version must be a positive integer")
    if raw > current:
        raise ValueError(f"{key}.schema_version {raw} is newer than supported version {current}")
    is_legacy = raw < current or declared_legacy
    if raw < current:
        classification = f"LEGACY_V{raw}"
    elif declared_legacy:
        classification = "LEGACY_DECLARED"
    else:
        classification = "CURRENT"
    return {
        "artifact_type": key,
        "current_version": current,
        "source_version": raw,
        "classification": classification,
        "is_legacy": is_legacy,
    }


def normalize_artifact_version(
    value: dict[str, Any],
    artifact_type: str,
    *,
    expected_version: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a current-version projection and its immutable legacy metadata."""

    info = classify_artifact_version(value, artifact_type, expected_version=expected_version)
    if value.get("legacy_migration") is False and info["is_legacy"]:
        raise ValueError(f"{info['artifact_type']} legacy input cannot set legacy_migration=false")
    result = dict(value)
    result["schema_version"] = info["current_version"]
    if info["is_legacy"]:
        result["legacy_migration"] = True
        result.setdefault("legacy_classification", info["classification"])
        if info["source_version"] is not None:
            result.setdefault("legacy_source_version", info["source_version"])
    return result, info


def preserve_projection_links(
    value: dict[str, Any],
    *,
    previous_id: str | None = None,
    previous_revision: int | None = None,
    previous_field: str = "supersedes_id",
) -> dict[str, Any]:
    """Preserve immutable links when a current projection supersedes an older one."""

    result = dict(value)
    if previous_id is not None:
        if not isinstance(previous_id, str) or not previous_id.strip():
            raise ValueError("previous artifact identity must be a non-empty string")
        for field in (previous_field, "supersedes_id"):
            supplied = result.get(field)
            if supplied is not None and supplied != previous_id:
                raise ValueError(f"{field} does not match the superseded artifact")
            result[field] = previous_id
    if previous_revision is not None:
        if isinstance(previous_revision, bool) or not isinstance(previous_revision, int) or previous_revision < 0:
            raise ValueError("previous artifact revision must be a non-negative integer")
        supplied = result.get("previous_revision")
        if supplied is not None and supplied != previous_revision:
            raise ValueError("previous_revision does not match the superseded artifact")
        result["previous_revision"] = previous_revision
    return result


def validate_artifact_payload(
    value: Any,
    schema: dict[str, Any],
    *,
    base_path: Path | None = None,
    artifact_type: str | None = None,
    expected_version: int | None = None,
    allow_legacy: bool = True,
) -> tuple[list[str], dict[str, Any] | None]:
    """Validate a payload while optionally applying a non-persisted legacy view."""

    candidate = value
    info: dict[str, Any] | None = None
    if artifact_type is not None:
        try:
            info = classify_artifact_version(value, artifact_type, expected_version=expected_version)
        except (TypeError, ValueError) as exc:
            return [f"$: {exc}"], None
        if info["is_legacy"] and not allow_legacy:
            return [f"$: {info['artifact_type']} is {info['classification']} and requires migration"], info
        # Review stage schemas may require schema_version even for a legacy
        # artifact.  Validate a projected copy; never mutate the caller.
        if info["is_legacy"] and isinstance(value, dict):
            properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
            additional = schema.get("additionalProperties", True) if isinstance(schema, dict) else True
            if "schema_version" in properties or additional is not False:
                candidate = dict(value)
                candidate.setdefault("schema_version", info["current_version"])
    errors = validate(candidate, schema, base_path=base_path)
    return errors, info


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
    parser.add_argument("--artifact-type")
    parser.add_argument("--expected-version", type=int)
    parser.add_argument("--require-current", action="store_true")
    args = parser.parse_args()
    try:
        payload = read_payload(args.input)
        schema = read_json(args.schema)
        errors, _ = validate_artifact_payload(
            payload,
            schema,
            base_path=Path(args.schema).resolve().parent,
            artifact_type=args.artifact_type,
            expected_version=args.expected_version,
            allow_legacy=not args.require_current,
        )
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
