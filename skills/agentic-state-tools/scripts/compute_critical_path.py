"""Compute a deterministic longest path for a validated dependency DAG."""

from __future__ import annotations

import argparse
import json
import sys

from graph_utils import critical_path, normalize_graph, topological_order
from runtime_utils import read_object


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        graph_id, revision, durations, edges = normalize_graph(read_object(args.input))
        order = topological_order(durations, edges)
        path, duration = critical_path(durations, edges, order)
        print(json.dumps({"graph_id": graph_id, "revision": revision, "topological_order": order, "critical_path": path, "critical_path_duration": duration}, indent=2))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"CRITICAL_PATH_INVALID: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
