"""Create a clean archive with a generated manifest."""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

EXCLUDED_PARTS = {
    "__pycache__",
    ".git",
    ".phongka",
    ".agent",
    ".idea",
    ".vscode",
    "node_modules",
    ".venv",
    "venv",
    "tmp",
    "temp",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".bak", ".swp"}


def include(path: Path, root: Path, output: Path) -> bool:
    if path.resolve() == output.resolve():
        return False
    if path.is_symlink():
        return False
    rel = path.relative_to(root)
    if rel.as_posix() == "MANIFEST.txt":
        return False
    if any(part in EXCLUDED_PARTS for part in rel.parts):
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    return path.is_file()


def unsafe_paths(root: Path) -> list[Path]:
    unsafe: list[Path] = []
    root_resolved = root.resolve()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            unsafe.append(path)
            continue
        resolved = path.resolve()
        if resolved != root_resolved and root_resolved not in resolved.parents:
            unsafe.append(path)
    return unsafe


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = Path(args.output).resolve()
    if not root.is_dir():
        print("PACKAGE_REJECTED: root is not a directory", file=sys.stderr)
        return 1
    unsafe = unsafe_paths(root)
    if unsafe:
        print(
            "PACKAGE_REJECTED: symlink or out-of-root path: "
            + ", ".join(str(path.relative_to(root)) for path in unsafe),
            file=sys.stderr,
        )
        return 1
    files = [path for path in sorted(root.rglob("*")) if include(path, root, output)]
    if not files:
        print("PACKAGE_REJECTED: no files selected", file=sys.stderr)
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = [path.relative_to(root).as_posix() for path in files]
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, rel in zip(files, manifest):
            archive.write(path, rel)
        archive.writestr("MANIFEST.txt", "\n".join(manifest) + "\n")
    print(
        json.dumps(
            {"status": "PACKAGED", "output": str(output), "files": len(files) + 1},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
