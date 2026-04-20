"""Long-call-chain detection — BFS reachability from entry points."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator

from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.base import IR


class LongCallChain(IR):
    """An entry point reaches >=N hops into the callee tree — refactor smell.

    "Depth" here is the BFS distance from the entry point to the deepest
    reachable callee (shortest path to that node). A project-independent
    threshold of 10 is the default — adjust via analyze kwarg if yours
    should be lower/higher.
    """

    entry_qname: str
    depth: int
    deepest_callee: str
    path: tuple[str, ...]


def find_long_call_chains(
    graph: AnalyzedGraph, threshold: int = 10
) -> Iterator[LongCallChain]:
    """Flag entry points whose BFS-reachable depth exceeds `threshold`.

    "Depth" is shortest-path distance from the entry to the deepest
    reachable callee. BFS naturally gives us that — O(V+E) per entry,
    O(entries * E) total. Cycles are handled by the global `visited`
    set so we never revisit a node.

    Threshold default is 10, tuned so most well-factored codebases are
    quiet and deeply-chained ones surface. No kwarg on the CLI yet; the
    AnalysisReport shape lets callers customise in Python.
    """
    resolved = graph.annotated.resolved
    for ep in graph.entry_points:
        deepest, path = _bfs_deepest(resolved, ep.qname)
        depth = len(path) - 1
        if depth >= threshold:
            yield LongCallChain(
                entry_qname=ep.qname,
                depth=depth,
                deepest_callee=deepest,
                path=path,
            )


def _bfs_deepest(resolved, start: str) -> tuple[str, tuple[str, ...]]:
    """BFS from `start`, return (deepest_node_qname, path_tuple)."""
    dist: dict[str, tuple[str, ...]] = {start: (start,)}
    q = deque([start])
    while q:
        node = q.popleft()
        for edge in resolved.get_callees(node):
            c = edge.callee_qname
            if c not in dist:
                dist[c] = dist[node] + (c,)
                q.append(c)
    deepest = max(dist, key=lambda k: len(dist[k]))
    return deepest, dist[deepest]
