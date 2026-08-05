"""Compatibility entry point for schema and artifact-version validation."""

from validate_payload import (
    classify_artifact_version,
    main,
    normalize_artifact_version,
    preserve_projection_links,
    validate_artifact_payload,
)

__all__ = [
    "classify_artifact_version",
    "normalize_artifact_version",
    "preserve_projection_links",
    "validate_artifact_payload",
]


if __name__ == "__main__":
    raise SystemExit(main())
