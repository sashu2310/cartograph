"""Reachability of project functions from the test tree.

Call with a graph built from `RunConfig(include_tests=True)`. Anything
reached only via dynamic dispatch (fixtures passing callables) won't
show up — static graph only.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator

from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.base import IR


class FunctionCoverage(IR):
    qname: str
    has_test_coverage: bool


def _is_test_module(module_name: str) -> bool:
    # Segment match, not prefix match — avoids false positives on
    # `mypackage.testing` or `contest.foo`.
    for segment in module_name.split("."):
        if segment == "tests" or segment.startswith(("tests_", "test_")):
            return True
        if segment.endswith("_test"):
            return True
    return False


def _collect_test_qnames(graph: AnalyzedGraph) -> set[str]:
    return {
        qname
        for qname, fn in graph.annotated.resolved.functions.items()
        if _is_test_module(fn.module)
    }


def _reachable_from(graph: AnalyzedGraph, roots: set[str]) -> set[str]:
    resolved = graph.annotated.resolved
    visited: set[str] = set()
    queue: deque[str] = deque(roots)
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        for edge_idx in resolved.callees_by_caller.get(node, ()):
            callee = resolved.edges[edge_idx].callee_qname
            if callee not in visited:
                queue.append(callee)
    return visited


def find_coverage(graph: AnalyzedGraph) -> Iterator[FunctionCoverage]:
    test_qnames = _collect_test_qnames(graph)
    reachable = _reachable_from(graph, test_qnames)
    for qname in sorted(graph.annotated.resolved.functions):
        fn = graph.annotated.resolved.functions[qname]
        if _is_test_module(fn.module):
            continue
        yield FunctionCoverage(
            qname=qname,
            has_test_coverage=qname in reachable,
        )
