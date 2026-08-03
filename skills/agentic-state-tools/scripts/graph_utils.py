"""Normalize and validate dependency graph contracts."""

from __future__ import annotations

import heapq
from typing import Any


def normalize_graph(value: dict[str, Any]) -> tuple[str, int, dict[str, int], list[tuple[str, str]]]:
    graph_id = value.get("graph_id")
    revision = value.get("revision")
    nodes_value = value.get("nodes")
    edges_value = value.get("edges")
    if not isinstance(graph_id, str) or not graph_id.strip():
        raise ValueError("graph_id must be a non-empty string")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("graph revision must be a non-negative integer")
    if not isinstance(nodes_value, list) or not isinstance(edges_value, list):
        raise ValueError("graph nodes and edges must be arrays")

    durations: dict[str, int] = {}
    for node in nodes_value:
        if isinstance(node, str):
            task_id, duration = node, 1
        elif isinstance(node, dict):
            task_id = node.get("task_id", node.get("id"))
            duration = node.get("duration", 1)
        else:
            raise ValueError("graph nodes must be strings or objects")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("graph node ID must be a non-empty string")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            raise ValueError(f"graph node duration must be a positive integer: {task_id}")
        if task_id in durations:
            raise ValueError(f"duplicate graph node: {task_id}")
        durations[task_id] = duration

    edges: list[tuple[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()
    for edge in edges_value:
        if not isinstance(edge, dict):
            raise ValueError("graph edges must be objects")
        source = edge.get("from", edge.get("source"))
        target = edge.get("to", edge.get("target"))
        if not isinstance(source, str) or not isinstance(target, str) or not source.strip() or not target.strip():
            raise ValueError("graph edge endpoints must be non-empty strings")
        if source not in durations or target not in durations:
            raise ValueError(f"graph edge references missing node: {source} -> {target}")
        pair = (source, target)
        if pair not in seen_edges:
            edges.append(pair)
            seen_edges.add(pair)
    return graph_id, revision, durations, edges


def topological_order(durations: dict[str, int], edges: list[tuple[str, str]]) -> list[str]:
    outgoing = {node: [] for node in durations}
    indegree = {node: 0 for node in durations}
    for source, target in edges:
        outgoing[source].append(target)
        indegree[target] += 1
    ready = [node for node, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        node = heapq.heappop(ready)
        order.append(node)
        for target in sorted(outgoing[node]):
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, target)
    if len(order) != len(durations):
        cycle_nodes = sorted(node for node, degree in indegree.items() if degree > 0)
        raise ValueError(f"dependency cycle detected: {' -> '.join(cycle_nodes)}")
    return order


def critical_path(durations: dict[str, int], edges: list[tuple[str, str]], order: list[str]) -> tuple[list[str], int]:
    def select(candidates: list[tuple[int, tuple[str, ...]]]) -> tuple[int, tuple[str, ...]]:
        longest = max(duration for duration, _ in candidates)
        paths = [path for duration, path in candidates if duration == longest]
        return longest, min(paths)

    predecessors = {node: [] for node in durations}
    for source, target in edges:
        predecessors[target].append(source)
    best: dict[str, tuple[int, tuple[str, ...]]] = {}
    for node in order:
        candidates = [(0, tuple())]
        for predecessor in sorted(predecessors[node]):
            previous_duration, previous_path = best[predecessor]
            candidates.append((previous_duration, previous_path))
        previous_duration, previous_path = select(candidates)
        if previous_path:
            path = previous_path + (node,)
        else:
            path = (node,)
        best[node] = (previous_duration + durations[node], path)
    duration, path = select(list(best.values()))
    return list(path), duration
