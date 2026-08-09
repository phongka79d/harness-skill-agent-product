"""Validate relative Markdown links across the portable skill package."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
FENCE_PATTERN = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")


def _link_targets(text: str) -> list[str]:
    """Return links outside fenced code blocks; code samples are not navigable links."""
    targets: list[str] = []
    fence: tuple[str, int] | None = None
    for line in text.splitlines():
        marker = FENCE_PATTERN.match(line)
        if fence is None:
            if marker is not None:
                token = marker.group(1)
                fence = (token[0], len(token))
                continue
            targets.extend(PATTERN.findall(line))
            continue
        if marker is not None:
            token = marker.group(1)
            if (
                token[0] == fence[0]
                and len(token) >= fence[1]
                and not line[marker.end() :].strip()
            ):
                fence = None
    return targets


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skills-root", required=True)
    args = parser.parse_args()
    root = Path(args.skills_root).expanduser().resolve()
    errors: list[str] = []
    for file in root.rglob("*.md"):
        text = file.read_text(encoding="utf-8")
        for target in _link_targets(text):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            clean = target.split("#", 1)[0]
            if clean and not (file.parent / clean).resolve().exists():
                errors.append(f"{file.relative_to(root)} -> {target}")
    if errors:
        print("MARKDOWN_LINKS_REJECTED\n" + "\n".join(errors), file=sys.stderr)
        return 1
    print("MARKDOWN_LINKS_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
