"""Import-cycle detection.

DFS with three-colour node state (0=white/unvisited, 1=gray/on-stack,
2=black/done). A back-edge into a gray node is a cycle; slice it out of
the stack and normalise so reruns produce stable output.
"""

from __future__ import annotations

from collections.abc import Iterator

from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.base import IR


class ImportCycle(IR):
    """A cycle in the project's module import graph.

    `modules` is the cycle in traversal order, normalised to start from
    the alphabetically smallest member so that reruns produce stable,
    diffable output.
    """

    modules: tuple[str, ...]


def find_import_cycles(graph: AnalyzedGraph) -> Iterator[ImportCycle]:
    """Detect cycles in the project's module import graph.

    Builds a directed graph of `module_name -> set of imported project
    modules` from Stage 1 imports, then DFS-walks looking for back-edges
    into nodes currently on the recursion stack. Each distinct cycle is
    reported once (normalised to start from the alphabetically smallest
    member so the output is stable across runs).

    Only in-project imports count — `import os`, `from numpy import ...`
    land outside the project and don't participate in cycles.
    """
    modules = graph.annotated.source_modules
    if not modules:
        return

    # Build adjacency: module_name -> sorted list of project modules it imports.
    import_graph: dict[str, list[str]] = {}
    for name, module in modules.items():
        deps: set[str] = set()
        for imp in module.imports:
            target = imp.module
            if not target:
                continue
            if target in modules:
                deps.add(target)
        import_graph[name] = sorted(deps)

    color = dict.fromkeys(import_graph, 0)
    stack: list[str] = []
    seen_cycles: set[tuple[str, ...]] = set()

    def dfs(node: str) -> None:
        color[node] = 1  # gray: on the current recursion stack
        stack.append(node)
        for dep in import_graph.get(node, ()):
            if dep not in color:
                continue
            if color[dep] == 1:
                try:
                    idx = stack.index(dep)
                except ValueError:
                    continue
                cycle = tuple(stack[idx:])
                seen_cycles.add(_normalise_cycle(cycle))
            elif color[dep] == 0:
                dfs(dep)
        color[node] = 2  # black: fully processed
        stack.pop()

    for start in sorted(import_graph):
        if color[start] == 0:
            dfs(start)

    for cycle in sorted(seen_cycles):
        yield ImportCycle(modules=cycle)


def _normalise_cycle(cycle: tuple[str, ...]) -> tuple[str, ...]:
    """Rotate the cycle so it starts with its alphabetically smallest module.
    Ensures `(a,b,c)` and `(c,a,b)` and `(b,c,a)` all normalise to `(a,b,c)`."""
    if not cycle:
        return cycle
    min_idx = min(range(len(cycle)), key=lambda i: cycle[i])
    return cycle[min_idx:] + cycle[:min_idx]
