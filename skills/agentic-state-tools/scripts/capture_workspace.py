"""Capture normalized file hashes for workspace evidence."""
from __future__ import annotations

import argparse
import json
import sys

from runtime_utils import fingerprint_file, resolve_workspace_context


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--path", action="append", default=[])
    args = parser.parse_args()
    try:
        if not args.path:
            raise ValueError("at least one --path is required")
        workspace_root, identity = resolve_workspace_context(args.project_root, task_id=args.task_id)
        items = [fingerprint_file(workspace_root, rel) for rel in args.path]
        normalized = [item["path"] for item in items]
        if len(normalized) != len(set(normalized)):
            raise ValueError("workspace paths must be unique after normalization")
        items.sort(key=lambda item: item["path"])
    except (OSError, ValueError, TypeError) as exc:
        print(f"WORKSPACE_REJECTED: {exc}", file=sys.stderr)
        return 1
    result = {"files": items}
    if identity is not None:
        result["worktree"] = identity
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
