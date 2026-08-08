"""Safely rename a legacy project/.agent runtime to project/.phongka."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        project = Path(args.project_root).expanduser().resolve()
        old = project / ".agent"
        new = project / ".phongka"
        result = {"legacy": str(old), "target": str(new), "applied": False}
        if old.is_symlink() or new.is_symlink():
            raise ValueError("runtime roots must not be symlinks")
        if not old.exists():
            result["status"] = "NO_LEGACY_RUNTIME"
        elif not old.is_dir():
            raise ValueError("legacy runtime root must be a directory")
        elif new.exists():
            result["status"] = "TARGET_ALREADY_EXISTS"
        elif not args.apply:
            result["status"] = "READY"
        else:
            old.rename(new)
            result.update(status="MIGRATED", applied=True)
    except (OSError, ValueError, TypeError) as exc:
        print(f"MIGRATION_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"NO_LEGACY_RUNTIME", "READY", "MIGRATED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
