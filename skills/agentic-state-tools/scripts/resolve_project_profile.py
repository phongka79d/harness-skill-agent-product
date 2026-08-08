"""Resolve an immutable workflow profile without external dependencies."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
from schema_validation import validate_file  # noqa: E402
from runtime_utils import canonical, write_json_atomic  # noqa: E402

DEFAULT_PROFILES = HERE.parents[1] / "profiles"
PROFILE_SCHEMA = HERE.parents[1] / "schemas" / "profile.schema.json"
ALIASES = {
    "quick-change": "quick_change",
    "course-project": "course_project",
    "internal-tool": "internal_tool",
    "high-risk": "high_risk",
}


def resolve_profile(
    profile_id: str, profiles_dir: str | Path = DEFAULT_PROFILES
) -> dict[str, Any]:
    canonical_id = ALIASES.get(profile_id.strip(), profile_id.strip().replace("-", "_"))
    if not canonical_id or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_" for ch in canonical_id):
        raise ValueError(f"invalid profile id: {profile_id}")
    path = Path(profiles_dir).resolve() / f"{canonical_id}.json"
    if not path.is_file():
        raise ValueError(f"unknown profile: {profile_id}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    validate_file(raw, PROFILE_SCHEMA, f"profile {canonical_id}")
    if raw.get("profile_id") != canonical_id:
        raise ValueError(f"profile id mismatch: {path.name}")
    result = dict(raw)
    result["profile_hash"] = hashlib.sha256(canonical(raw).encode("utf-8")).hexdigest()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--profiles-dir", default=str(DEFAULT_PROFILES))
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        result = resolve_profile(args.profile, args.profiles_dir)
        if args.output:
            write_json_atomic(args.output, result)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"PROFILE_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
