"""Validate that Wiki markdown links stay inside the installed skills tree."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def validate_links(root: str | Path) -> list[str]:
    base = Path(root).resolve()
    if not base.is_dir():
        return [f"Wiki root does not exist: {base}"]
    # The Wiki routes to sibling skill packages, but never outside /skills.
    # Keep temporary/test roots strict so this helper remains useful outside the
    # installed agentic-engineering-wiki package.
    boundary = base.parent if base.name == "agentic-engineering-wiki" else base
    errors: list[str] = []
    for document in sorted(base.rglob("*.md")):
        for raw_target in LINK_RE.findall(document.read_text(encoding="utf-8")):
            target = raw_target.split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:")):
                errors.append(f"{document.relative_to(base)} has non-local link: {raw_target}")
                continue
            if target.replace("\\", "/").startswith(".agent/wiki/") or target.startswith("/"):
                errors.append(f"{document.relative_to(base)} escapes skills boundary: {raw_target}")
                continue
            resolved = (document.parent / target).resolve()
            try:
                resolved.relative_to(boundary)
            except ValueError:
                errors.append(f"{document.relative_to(base)} escapes skills boundary: {raw_target}")
                continue
            if not resolved.is_file():
                errors.append(f"{document.relative_to(base)} links to missing file: {raw_target}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        errors = validate_links(args.root)
    except (OSError, UnicodeError) as exc:
        print(f"WIKI_INVALID: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"WIKI_INVALID: {error}", file=sys.stderr)
        return 1
    print("WIKI_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
