"""Internal validated JSON artifact writer for initialized .agent files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime_utils import ensure_runtime_initialized, read_json, write_json_atomic
from validate_payload import validate


def write_validated(
    project_root: str,
    relative_path: str,
    payload: dict[str, Any],
    schema_path: str | Path,
) -> Path:
    root = ensure_runtime_initialized(project_root)
    target = (root / relative_path).resolve()
    if root.resolve() not in target.parents:
        raise ValueError("artifact path must remain inside .agent")
    schema = read_json(schema_path)
    errors = validate(payload, schema, base_path=Path(schema_path).resolve().parent)
    if errors:
        raise ValueError("; ".join(errors))
    write_json_atomic(target, payload)
    return target
