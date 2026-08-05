"""Reject vague planning instructions unless precise, testable detail accompanies them."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from runtime_utils import read_payload


VAGUE_PATTERNS = (
    re.compile(r"\bTBD\b", re.IGNORECASE),
    re.compile(r"\bTODO\b", re.IGNORECASE),
    re.compile(r"\bhandle\s+edge\s+cases\b", re.IGNORECASE),
    re.compile(r"\badd\s+validation\b", re.IGNORECASE),
    re.compile(r"\bwrite\s+tests?\b", re.IGNORECASE),
    re.compile(r"\bmake\s+it\s+robust\b", re.IGNORECASE),
    re.compile(r"\bsimilar\s+to\s+the\s+previous\s+task\b", re.IGNORECASE),
    re.compile(r"\bimplement\s+as\s+appropriate\b", re.IGNORECASE),
)

PRECISION_PATTERNS = (
    re.compile(r"(?:python|pytest|unittest|npm|pnpm|yarn|cargo|go|make|dotnet|bash|pwsh|powershell)\b", re.IGNORECASE),
    re.compile(r"(?:exit\s*code|status|acceptance|criterion|expected|assert|command|path|file|owner|deadline)\b", re.IGNORECASE),
    re.compile(r"\b[A-Z]{2,}[A-Z0-9._-]*[-_][A-Z0-9._-]+\b"),
    re.compile(r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
)


def _has_precise_detail(text: str) -> bool:
    return any(pattern.search(text) for pattern in PRECISION_PATTERNS)


def find_placeholders(value: Any, path: str = "$") -> list[str]:
    """Return paths containing vague instructions without local precision."""
    findings: list[str] = []
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in VAGUE_PATTERNS) and not _has_precise_detail(value):
            findings.append(f"{path}: vague placeholder instruction")
    elif isinstance(value, dict):
        for key, child in value.items():
            findings.extend(find_placeholders(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(find_placeholders(child, f"{path}[{index}]"))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        payload = read_payload(args.input)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"PLACEHOLDERS_INVALID: {exc}", file=sys.stderr)
        return 2
    findings = find_placeholders(payload)
    if findings:
        for finding in findings:
            print(f"PLACEHOLDERS_INVALID: {finding}", file=sys.stderr)
        return 1
    print("PLACEHOLDERS_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
