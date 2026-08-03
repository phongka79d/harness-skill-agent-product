"""Small dependency-free scanner for secrets and sensitive context paths."""

from __future__ import annotations

import json
import re
from typing import Any


SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|auth(?:orization)?|bearer|cookie|password|passwd|secret|private[_-]?key|database[_-]?url|client[_-]?secret|cloud[_-]?credential)",
    re.IGNORECASE,
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|password|passwd|secret|database[_-]?url|client[_-]?secret)\b\s*[:=]\s*[\"']?[^\s\"']+"),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
SENSITIVE_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519", "credentials", "credentials.json", "secrets.json"}


def is_sensitive_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value.replace("\\", "/").strip().lower()
    parts = [part for part in normalized.split("/") if part]
    if any(part in SENSITIVE_NAMES for part in parts):
        return True
    basename = parts[-1] if parts else normalized
    return basename.endswith((".pem", ".key", ".p12", ".pfx")) or basename.startswith(".env")


def _is_binary_text(value: str) -> bool:
    return "\x00" in value or sum(ord(char) < 9 or 13 < ord(char) < 32 for char in value) > max(2, len(value) // 20)


def scan_text(value: str, path: str = "") -> list[str]:
    findings: list[str] = []
    if _is_binary_text(value):
        findings.append(f"{path}:binary")
    if any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS):
        findings.append(f"{path}:secret")
    return findings


def scan_value(value: Any, path: str = "$", *, key_hint: str | None = None) -> list[str]:
    findings: list[str] = []
    if key_hint and SENSITIVE_KEY.search(key_hint):
        if isinstance(value, (str, bytes)) and value:
            findings.append(f"{path}:sensitive-key")
        elif isinstance(value, (dict, list)) and value:
            findings.append(f"{path}:sensitive-key")
    if isinstance(value, bytes):
        findings.append(f"{path}:binary")
    elif isinstance(value, str):
        findings.extend(scan_text(value, path))
    elif isinstance(value, dict):
        for key, child in value.items():
            findings.extend(scan_value(child, f"{path}.{key}", key_hint=str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(scan_value(child, f"{path}[{index}]"))
    return sorted(set(findings))


def context_security_errors(payload: Any, *, max_bytes: int) -> list[str]:
    errors = scan_value(payload)
    if isinstance(payload, dict):
        code_context = payload.get("code_context")
        if isinstance(code_context, dict):
            files = code_context.get("files_to_read", [])
            if isinstance(files, list):
                for path in files:
                    if is_sensitive_path(path):
                        errors.append("code_context.files_to_read contains a sensitive path")
            contents = code_context.get("file_contents", {})
            if isinstance(contents, dict):
                for path, content in contents.items():
                    if is_sensitive_path(path):
                        errors.append("code_context.file_contents contains a sensitive path")
                    errors.extend(scan_value(content, f"$.code_context.file_contents.{path}"))
    try:
        size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        errors.append("context payload is not serializable")
    else:
        if size > max_bytes:
            errors.append("context payload exceeds configured byte budget")
    return sorted(set(errors))
