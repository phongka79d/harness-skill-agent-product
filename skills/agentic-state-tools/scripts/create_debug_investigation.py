"""Write a validated debug-investigation.json artifact."""
from __future__ import annotations
import argparse, json, sys
from artifact_writer import write_artifact

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        result = write_artifact(args.project_root, args.input, "debug-investigation.schema.json", "debug-investigation.json", "DEBUG_INVESTIGATION_WRITTEN")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ARTIFACT_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
