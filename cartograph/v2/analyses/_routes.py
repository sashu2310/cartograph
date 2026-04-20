"""FastAPI / Flask / Ninja route collision detection."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator

from cartograph.v2.ir.analyzed import AnalyzedGraph, ApiRouteEntry
from cartograph.v2.ir.base import IR


class PathCollision(IR):
    """Two or more API route handlers registered at the same method + path.

    Detected purely from Stage 4's ApiRouteEntry list (grouped by
    (method, path)). Can surface false positives on codebases with
    multiple independent FastAPI apps sharing URL shapes (e.g.
    tutorial collections). Real collisions in a single app are a
    silent bug — last registration wins at runtime.
    """

    method: str
    path: str
    handlers: tuple[str, ...]


def find_path_collisions(graph: AnalyzedGraph) -> Iterator[PathCollision]:
    """Flag (method, path) pairs registered by >=2 handlers.

    Pure group-by on Stage 4's ApiRouteEntry list. One entry per
    collision, sorted by (method, path) for stable output.
    """
    by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
    for ep in graph.entry_points:
        if isinstance(ep, ApiRouteEntry):
            by_key[(ep.method, ep.path)].append(ep.qname)

    for (method, path), qnames in sorted(by_key.items()):
        if len(qnames) > 1:
            yield PathCollision(
                method=method,
                path=path,
                handlers=tuple(sorted(qnames)),
            )
