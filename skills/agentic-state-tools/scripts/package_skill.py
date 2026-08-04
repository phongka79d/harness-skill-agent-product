"""Create a deterministic, manifest-driven ZIP of the portable skill package."""

from __future__ import annotations

import argparse
import ast
import sys
import zipfile
from pathlib import Path

from secret_scanner import scan_text


MANIFEST_NAME = "MANIFEST.txt"
PACKAGE_ROOTS = ("skills", "docs", "tests")
TOP_LEVEL_MEMBERS = {MANIFEST_NAME, "run_tests.py", "README.md"}
SKILL_MEMBER_DIRECTORIES = {
    "config",
    "configuration",
    "examples",
    "references",
    "refs",
    "schemas",
    "scripts",
}
BLOCKED_PARTS = {
    ".agent",
    ".git",
    ".pytest_cache",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "runtime",
}
BLOCKED_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials",
    "credentials.json",
    "secrets.json",
    "deployment.test.json",
}
BLOCKED_SUFFIXES = {".coverage", ".p12", ".pfx", ".pem", ".pyc", ".pyo", ".secret", ".tmp", ".key", ".log"}
PYTHON_SECRET_NAMES = {
    "api_key",
    "api_token",
    "access_token",
    "authorization",
    "bearer",
    "client_secret",
    "database_url",
    "password",
    "passwd",
    "private_key",
    "secret",
    "token",
}
PYTHON_PLACEHOLDER_MARKERS = {"example", "test", "dummy", "placeholder", "secret", "token", "password", "material", "opaque", "value"}


def _normal_member(value: str) -> str:
    member = value.strip().replace("\\", "/")
    if not member or member.startswith("/") or "../" in f"{member}/" or member == "..":
        raise ValueError(f"invalid manifest member: {value!r}")
    return member


def read_manifest(root: str | Path) -> list[str]:
    package_root = Path(root).expanduser().resolve()
    manifest_path = package_root / MANIFEST_NAME
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("manifest is missing")
    members: list[str] = []
    seen: set[str] = set()
    try:
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError("manifest is not readable text") from exc
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        member = _normal_member(value)
        if member in seen:
            raise ValueError(f"manifest contains duplicate member: {member}")
        seen.add(member)
        members.append(member)
    if MANIFEST_NAME not in seen:
        raise ValueError("manifest must list MANIFEST.txt")
    return sorted(members)


def _blocked(relative: Path) -> bool:
    parts = {part.casefold() for part in relative.parts}
    name = relative.name.casefold()
    skill_local_tests = relative.parts[0].casefold() == "skills" and any(
        part.casefold() == "tests" for part in relative.parts[2:]
    )
    return (
        bool(parts & BLOCKED_PARTS)
        or skill_local_tests
        or name in BLOCKED_NAMES
        or any(name.endswith(suffix) for suffix in BLOCKED_SUFFIXES)
    )


def _allowed_member(relative: Path) -> bool:
    if not relative.parts or _blocked(relative):
        return False
    value = relative.as_posix()
    if value in TOP_LEVEL_MEMBERS:
        return True
    if relative.parts[0] not in PACKAGE_ROOTS:
        return False
    if relative.parts[0] == "docs":
        return relative.suffix.casefold() in {".md", ".json", ".txt", ".yaml", ".yml"}
    if relative.parts[0] == "tests":
        return relative.suffix.casefold() in {".py", ".json", ".yaml", ".yml", ".md", ".txt"}
    if relative.parts[0] == "skills":
        if len(relative.parts) < 3:
            return False
        if relative.name in {"SKILL.md", "README.md", MANIFEST_NAME}:
            return True
        return relative.parts[2].casefold() in SKILL_MEMBER_DIRECTORIES
    return False


def _candidate_files(package_root: Path) -> list[Path]:
    candidates: list[Path] = []
    for name in PACKAGE_ROOTS:
        directory = package_root / name
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            relative = path.relative_to(package_root)
            if path.is_file() and not path.is_symlink() and _allowed_member(relative):
                candidates.append(path)
    for name in TOP_LEVEL_MEMBERS:
        path = package_root / name
        if path.is_file() and not path.is_symlink():
            candidates.append(path)
    return sorted(set(candidates), key=lambda path: path.relative_to(package_root).as_posix())


def _forbidden_files(package_root: Path) -> list[Path]:
    forbidden: list[Path] = []
    for name in PACKAGE_ROOTS:
        directory = package_root / name
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            relative = path.relative_to(package_root)
            if path.is_file() and _blocked(relative):
                forbidden.append(path)
    for path in package_root.iterdir():
        relative = path.relative_to(package_root)
        if relative.name.casefold() == ".agent":
            forbidden.append(path)
        elif path.is_file() and _blocked(relative):
            forbidden.append(path)
    return sorted(set(forbidden), key=lambda path: path.relative_to(package_root).as_posix())


def _validate_content(package_root: Path, path: Path) -> None:
    relative = path.relative_to(package_root)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"package member is not readable text: {relative.as_posix()}") from exc
    findings = scan_text(text, relative.as_posix())
    if path.suffix.casefold() == ".py":
        findings = [
            finding
            for finding in findings
            if not finding.endswith(":token_assignment") and not finding.endswith(":secret")
        ]
        try:
            tree = ast.parse(text, filename=relative.as_posix())
        except SyntaxError as exc:
            raise ValueError(f"package member contains invalid Python: {relative.as_posix()}") from exc
        for node in ast.walk(tree):
            target_names: list[str] = []
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        target_names.append(target.id.casefold())
            if not any(name in PYTHON_SECRET_NAMES for name in target_names):
                continue
            value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
            literal = value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else None
            if literal and len(literal) >= 16 and not any(marker in literal.casefold() for marker in PYTHON_PLACEHOLDER_MARKERS):
                findings.append(f"{relative.as_posix()}:token_assignment")
                break
    if findings:
        raise ValueError("sensitive content found in package member: " + "; ".join(findings))


def package_members(root: str | Path) -> list[str]:
    package_root = Path(root).expanduser().resolve()
    manifest_members = read_manifest(package_root)
    manifest_set = set(manifest_members)
    forbidden = _forbidden_files(package_root)
    listed_forbidden = [
        path for path in forbidden
        if path.relative_to(package_root).as_posix() in manifest_set
    ]
    if listed_forbidden:
        relative = listed_forbidden[0].relative_to(package_root).as_posix()
        raise ValueError(f"forbidden package member: {relative}")
    for member in manifest_members:
        path = package_root / Path(member)
        if not _allowed_member(Path(member)):
            raise ValueError(f"manifest member is outside the package allowlist: {member}")
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"manifest member is missing: {member}")
        _validate_content(package_root, path)

    candidates = _candidate_files(package_root)
    candidate_names = {path.relative_to(package_root).as_posix() for path in candidates}
    unlisted = sorted(candidate_names - manifest_set)
    if unlisted:
        raise ValueError("unlisted package member: " + unlisted[0])
    return sorted(manifest_set)


def _validate_archive(package_root: Path, output: Path, members: list[str]) -> None:
    try:
        with zipfile.ZipFile(output, "r") as archive:
            archived = archive.namelist()
            if archived != members:
                raise ValueError("archive member order or membership differs from MANIFEST.txt")
            for member in archived:
                if not _allowed_member(Path(member)) or member not in members:
                    raise ValueError(f"archive contains an unlisted member: {member}")
                if archive.read(member) != (package_root / Path(member)).read_bytes():
                    raise ValueError(f"archive content differs from source: {member}")
    except zipfile.BadZipFile as exc:
        raise ValueError("release archive is not a valid ZIP") from exc


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
            archive.writestr(info, (package_root / Path(member)).read_bytes())
    _validate_archive(package_root, destination, members)
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
