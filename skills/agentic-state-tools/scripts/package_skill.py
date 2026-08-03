"""Create a deterministic allowlisted ZIP of the portable skill package."""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

from secret_scanner import scan_text


ALLOWED_ROOTS = {"skills", "docs"}
ALLOWED_EXTENSIONS = {".md", ".json", ".yaml", ".yml", ".py", ".txt", ".jsonl"}
BLOCKED_PARTS = {".git", ".agent", "__pycache__", ".pytest_cache", "build", "dist", "node_modules", "tests"}
BLOCKED_NAMES = {".env", ".env.local", ".env.production", "credentials.json", "secrets.json", "deployment.test.json"}
BLOCKED_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".secret", ".key", ".pem", ".p12", ".pfx"}


def _is_allowed(path: Path, root: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    relative = path.relative_to(root)
    if not relative.parts or relative.parts[0] not in ALLOWED_ROOTS:
        return False
    if any(part in BLOCKED_PARTS for part in relative.parts):
        return False
    name = path.name.lower()
    if name in BLOCKED_NAMES or any(name.endswith(suffix) for suffix in BLOCKED_SUFFIXES):
        return False
    return path.suffix.lower() in ALLOWED_EXTENSIONS


def package_members(root: str | Path) -> list[str]:
    package_root = Path(root).expanduser().resolve()
    candidates: list[Path] = []
    for name in sorted(ALLOWED_ROOTS):
        directory = package_root / name
        if directory.is_dir():
            candidates.extend(path for path in directory.rglob("*") if _is_allowed(path, package_root))
    members: list[str] = []
    for path in sorted(candidates):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"package member is not readable text: {path}") from exc
        findings = scan_text(text, path.relative_to(package_root).as_posix())
        if findings:
            raise ValueError("sensitive content found in package member: " + "; ".join(findings))
        members.append(path.relative_to(package_root).as_posix())
    return members


def build_package(root: str | Path, output: str | Path) -> Path:
    package_root = Path(root).expanduser().resolve()
    destination = Path(output).expanduser().resolve()
    members = package_members(package_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for member in members:
            info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, (package_root / member).read_bytes())
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        output = build_package(args.root, args.output)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"PACKAGE_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"PACKAGE_WRITTEN: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
