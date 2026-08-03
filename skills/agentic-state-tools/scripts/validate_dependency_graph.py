"""Validate planning dependency relationships without writing runtime state."""

from __future__ import annotations

import argparse
import json
import sys

from graph_utils import normalize_graph, topological_order
from runtime_utils import read_object
from validate_planning import validate_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        value = read_object(args.input)
        if "graph_id" in value:
            _, _, durations, edges = normalize_graph(value)
            topological_order(durations, edges)
            errors = []
        else:
            errors = validate_manifest(value)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"DEPENDENCY_GRAPH_INVALID: {exc}", file=sys.stderr)
        return 1
    graph_errors = [error for error in errors if "dependency" in error or "cycle" in error]
    if graph_errors:
        for error in graph_errors:
            print(f"DEPENDENCY_GRAPH_INVALID: {error}", file=sys.stderr)
        return 1
    print("DEPENDENCY_GRAPH_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
