"""Validate dispatch records against the dispatch contract before policy checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from validate_payload import validate


DISPATCH_SCHEMA = Path(__file__).resolve().parents[1] / "schemas" / "dispatch.schema.json"


def validate_dispatch_schema(dispatch: Any) -> None:
    schema = json.loads(DISPATCH_SCHEMA.read_text(encoding="utf-8"))
    errors = validate(dispatch, schema)
    if errors:
        raise ValueError("dispatch schema validation failed: " + "; ".join(errors))
