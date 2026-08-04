"""Safe, dependency-free secret scanning and redaction at persistence boundaries."""

from __future__ import annotations

import json
import os
import re
from typing import Any


SECRET_CATEGORIES = frozenset(
    {
        "private_key",
        "jwt",
        "cookie_header",
        "credentialed_url",
        "database_credential",
        "long_base64",
        "token_assignment",
    }
)
REDACTION_ACTIONS = frozenset({"REJECT", "REDACT"})
REDACTED = "[REDACTED]"

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.IGNORECASE,
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")
_COOKIE_HEADER = re.compile(r"(?im)(?:^|\b)(?:cookie|set-cookie)\s*:\s*[^\r\n]+")
_DATABASE_URL = re.compile(
    r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis)://[^\s:@]+:[^\s@]+@[^\s]+",
    re.IGNORECASE,
)
_CREDENTIALED_URL = re.compile(
    r"\b(?:https?|ftp)://(?![^\s/:]+://)[^/\s:@]+:[^@\s]+@[^\s]+",
    re.IGNORECASE,
)
_LONG_BASE64 = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/=]{48,}(?![A-Za-z0-9+/=_-])")
_TOKEN_ASSIGNMENT = re.compile(
    r"(?i)[\"']?\b(?:api[_-]?key|api[_-]?token|access[_-]?token|auth(?:orization)?|bearer|client[_-]?secret|password|passwd|secret|token)\b[\"']?"
    r"\s*[:=]\s*(?:(?:bearer)\s+[^\s,;]+|\"[^\"\r\n]{4,}\"|'[^'\r\n]{4,}'|(?=[A-Za-z0-9._~+/=-]*[0-9._~+/=-])[A-Za-z0-9._~+/=-]{4,})"
)

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", _PRIVATE_KEY),
    ("jwt", _JWT),
    ("cookie_header", _COOKIE_HEADER),
    ("database_credential", _DATABASE_URL),
    ("credentialed_url", _CREDENTIALED_URL),
    ("long_base64", _LONG_BASE64),
    ("token_assignment", _TOKEN_ASSIGNMENT),
)

_SENSITIVE_KEY_CATEGORIES = {
    "api_key": "token_assignment",
    "api_keys": "token_assignment",
    "api_token": "token_assignment",
    "api_tokens": "token_assignment",
    "access_token": "token_assignment",
    "authorization": "token_assignment",
    "bearer": "token_assignment",
    "client_secret": "token_assignment",
    "cloud_credential": "token_assignment",
    "cookie": "cookie_header",
    "credentials": "token_assignment",
    "database_url": "database_credential",
    "password": "token_assignment",
    "passwd": "token_assignment",
    "private_key": "private_key",
    "secret": "token_assignment",
    "token": "token_assignment",
}

_CODE_BLOCK = re.compile(r"(?ms)(?P<open>```[^\n]*\n)(?P<body>.*?)(?P<close>```)")


def _normal_path(path: str) -> str:
    return path or "$"


def _path_child(path: str, key: str | int) -> str:
    path = _normal_path(path)
    if isinstance(key, int):
        return f"{path}[{key}]"
    return f"{path}.{key}"


def _key_category(key: str) -> str | None:
    normalized = re.sub(r"[-\s]", "_", key.casefold())
    return _SENSITIVE_KEY_CATEGORIES.get(normalized)


def _is_hex_digest(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{48,}", value))


def _text_categories(value: str) -> set[str]:
    categories: set[str] = set()
    for category, pattern in _PATTERNS:
        for match in pattern.finditer(value):
            matched = match.group(0)
            if category == "long_base64" and _is_hex_digest(matched):
                continue
            categories.add(category)
            break
    return categories


def _json_object_or_array(value: str) -> dict[str, Any] | list[Any] | None:
    candidate = value.strip()
    if not candidate or candidate[0] not in "[{" or candidate[-1] not in "]}":
        return None
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _json_lines(value: str) -> list[Any] | None:
    lines = [line for line in value.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    parsed: list[Any] = []
    for line in lines:
        try:
            item = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(item, (dict, list)):
            return None
        parsed.append(item)
    return parsed


def _scan_text(value: str, path: str) -> set[tuple[str, str]]:
    findings = {(path, category) for category in _text_categories(value)}

    parsed = _json_object_or_array(value)
    if parsed is not None:
        findings.update((item["path"], item["category"]) for item in scan_value(parsed, path))
    else:
        records = _json_lines(value)
        if records is not None:
            for index, record in enumerate(records):
                record_path = f"{path}[{index}]"
                findings.update((item["path"], item["category"]) for item in scan_value(record, record_path))

        for index, match in enumerate(_CODE_BLOCK.finditer(value)):
            body = match.group("body")
            parsed_block = _json_object_or_array(body)
            if parsed_block is not None:
                block_path = f"{path}.code_block[{index}]"
                findings.update((item["path"], item["category"]) for item in scan_value(parsed_block, block_path))
    return findings


def scan_value(value: Any, path: str = "$", *, key_hint: str | None = None) -> list[dict[str, str]]:
    """Return only safe ``{path, category}`` metadata for all findings."""

    path = _normal_path(path)
    findings: set[tuple[str, str]] = set()
    if key_hint and value != REDACTED:
        category = _key_category(key_hint)
        if category is not None and isinstance(value, (str, bytes)) and value not in (None, ""):
            findings.add((path, category))

    if isinstance(value, bytes):
        findings.add((path, "long_base64"))
    elif isinstance(value, str) and value != REDACTED:
        findings.update(_scan_text(value, path))
    elif isinstance(value, dict):
        for key, child in value.items():
            child_path = _path_child(path, str(key))
            findings.update(
                (item["path"], item["category"])
                for item in scan_value(child, child_path, key_hint=str(key))
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.update((item["path"], item["category"]) for item in scan_value(child, _path_child(path, index)))

    return [
        {"path": finding_path, "category": category}
        for finding_path, category in sorted(findings)
    ]


def _redact_text(value: str) -> str:
    redacted = value
    for category, pattern in _PATTERNS:
        def replacement(match: re.Match[str]) -> str:
            matched = match.group(0)
            if category == "long_base64" and _is_hex_digest(matched):
                return matched
            return REDACTED

        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_value(value: Any, path: str = "$", *, key_hint: str | None = None) -> Any:
    """Recursively replace secret-bearing values with ``[REDACTED]``."""

    if key_hint and _key_category(key_hint) is not None and isinstance(value, (str, bytes)) and value not in (None, ""):
        return REDACTED
    if isinstance(value, bytes):
        return REDACTED
    if isinstance(value, dict):
        return {
            key: redact_value(child, _path_child(path, str(key)), key_hint=str(key))
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_value(child, _path_child(path, index)) for index, child in enumerate(value)]
    if not isinstance(value, str):
        return value

    parsed = _json_object_or_array(value)
    if parsed is not None:
        return json.dumps(redact_value(parsed, path), ensure_ascii=False, separators=(",", ":"))
    records = _json_lines(value)
    if records is not None:
        return "\n".join(json.dumps(redact_value(item, f"{path}[{index}]"), ensure_ascii=False, separators=(",", ":")) for index, item in enumerate(records))

    def redact_code_block(match: re.Match[str]) -> str:
        body = match.group("body")
        parsed_block = _json_object_or_array(body)
        if parsed_block is None:
            return match.group(0)
        redacted_block = json.dumps(redact_value(parsed_block, f"{path}.code_block"), ensure_ascii=False, indent=2)
        return f"{match.group('open')}{redacted_block}\n{match.group('close')}"

    value = _CODE_BLOCK.sub(redact_code_block, value)
    return _redact_text(value)


def redaction_report(value: Any, *, action: str = "REDACT", path: str = "$") -> list[dict[str, str]]:
    """Return only ``{path, category, action}``; never include matched content."""

    normalized_action = str(action).upper()
    if normalized_action not in REDACTION_ACTIONS:
        raise ValueError(f"redaction action must be one of {sorted(REDACTION_ACTIONS)}")
    return [
        {"path": item["path"], "category": item["category"], "action": normalized_action}
        for item in scan_value(value, path)
    ]


def redaction_mode(value: str | None = None) -> str:
    selected = value or os.environ.get("AGENTIC_REDACTION_MODE") or os.environ.get("AGENTIC_REDACTION_POLICY") or "REJECT"
    mode = str(selected).upper()
    if mode not in REDACTION_ACTIONS:
        raise ValueError(f"redaction mode must be one of {sorted(REDACTION_ACTIONS)}")
    return mode


def sanitize_for_persistence(value: Any, *, mode: str | None = None) -> tuple[Any, list[dict[str, str]]]:
    """Apply the configured policy and keep rejection/report text secret-free."""

    normalized_mode = redaction_mode(mode)
    report = redaction_report(value, action=normalized_mode)
    if report and normalized_mode == "REJECT":
        details = ", ".join(f"{item['path']}:{item['category']}" for item in report)
        raise ValueError(f"secret scan rejected sensitive value: {details}")
    return (redact_value(value) if report else value), report
