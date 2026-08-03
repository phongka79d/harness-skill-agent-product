"""Canonical risk-flag vocabulary shared by planning and review contracts."""

from __future__ import annotations

from typing import Any


RISK_FLAG_KEYS = frozenset({
    "authentication", "authorization", "database", "schema_migration",
    "destructive_operation", "deployment", "security_sensitive", "external_api",
    "payments", "personal_data", "concurrency", "shared_state", "infrastructure",
})


def normalize_risk_flags(value: object) -> dict[str, bool]:
    """Validate risk flags and return a deterministic canonical mapping."""
    if not isinstance(value, dict):
        raise ValueError("risk_flags must be an object")
    normalized: dict[str, bool] = {}
    for key, flag in value.items():
        if not isinstance(key, str):
            raise ValueError("risk_flags keys must be strings")
        if key not in RISK_FLAG_KEYS:
            raise ValueError(f"unknown risk flag: {key}")
        if not isinstance(flag, bool):
            raise ValueError(f"risk_flags.{key} must be boolean")
        normalized[key] = flag
    return dict(sorted(normalized.items()))
