"""Resolve a named project profile into immutable, hashable metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from runtime_utils import write_json_atomic


DEFAULT_PROFILES = Path(__file__).resolve().parents[1] / "profiles"

PROFILE_ALIASES = {
    "course-project": "course_project",
    "high-risk": "high_risk",
    "internal-tool": "internal_tool",
    "quick-change": "quick_change",
}

VALID_TDD_MODES = {"MANDATORY", "REQUIRED_IF_HARNESS", "EXCEPTION_ALLOWED"}
VALID_BROAD_SUITE_MODES = {"MANDATORY", "RISK_BASED", "FOCUSED"}


def load_data(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ValueError("profile is not JSON-compatible YAML and PyYAML is unavailable") from exc
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"profile must be an object: {path}")
    return value


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def resolve_profile(profile_id: str, profiles_dir: str | Path = DEFAULT_PROFILES) -> dict[str, Any]:
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError("profile must be a non-empty string")
    requested_id = profile_id.strip()
    canonical_id = PROFILE_ALIASES.get(requested_id, requested_id)
    if not (Path(profiles_dir) / f"{canonical_id}.yaml").is_file() and "-" in canonical_id:
        canonical_id = canonical_id.replace("-", "_")
    path = Path(profiles_dir) / f"{canonical_id}.yaml"
    if not path.is_file():
        raise ValueError(f"unknown project profile: {requested_id}")
    raw = load_data(path)
    if raw.get("profile_id") != canonical_id:
        raise ValueError(f"profile_id does not match filename: {path.name}")
    version = raw.get("version")
    quality_level = raw.get("quality_level")
    project_profile = raw.get("project_profile")
    threshold = raw.get("default_threshold_percent")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("profile.version must be a non-empty string")
    if not isinstance(quality_level, str) or not quality_level.strip():
        raise ValueError("profile.quality_level must be a non-empty string")
    if not isinstance(project_profile, dict):
        raise ValueError("profile.project_profile must be an object")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 100:
        raise ValueError("profile.default_threshold_percent must be between 0 and 100")
    verification_policy = raw.get("verification_policy")
    if not isinstance(verification_policy, dict):
        raise ValueError("profile.verification_policy must be an object")
    tdd_mode = verification_policy.get("tdd_mode")
    broad_suite_mode = verification_policy.get("broad_suite_mode")
    if tdd_mode not in VALID_TDD_MODES:
        raise ValueError("profile.verification_policy.tdd_mode is invalid")
    if broad_suite_mode not in VALID_BROAD_SUITE_MODES:
        raise ValueError("profile.verification_policy.broad_suite_mode is invalid")
    allowed_exceptions = verification_policy.get("allowed_exception_types")
    behavior_change_types = verification_policy.get("behavior_change_types")
    if (
        not isinstance(allowed_exceptions, list)
        or not allowed_exceptions
        or any(not isinstance(item, str) or not item.strip() for item in allowed_exceptions)
    ):
        raise ValueError("profile.verification_policy.allowed_exception_types must be a non-empty string array")
    if (
        not isinstance(behavior_change_types, list)
        or not behavior_change_types
        or any(not isinstance(item, str) or not item.strip() for item in behavior_change_types)
    ):
        raise ValueError("profile.verification_policy.behavior_change_types must be a non-empty string array")
    profile_hash = hashlib.sha256(canonical(raw).encode("utf-8")).hexdigest()
    return {
        "profile_id": canonical_id,
        "profile_version": version,
        "profile_hash": profile_hash,
        "project_profile": project_profile,
        "quality_level": quality_level,
        "default_threshold_percent": threshold,
        "verification_policy": verification_policy,
    }


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
        print(f"PROFILE_RESOLUTION_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
