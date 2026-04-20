"""ORM analyses — N+1, hotspots, mixed operations, async-boundary crossings.

All four fire only on codebases where the ORM annotator found something —
`_iter_orm_by_function` yields an empty iterator otherwise.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from typing import Literal

from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.annotated import OrmOperationLabel
from cartograph.v2.ir.base import IR

OrmOp = Literal["read", "write", "delete"]


class NPlusOneCandidate(IR):
    """A single function reads the same model N>=2 times — likely a loop."""

    qname: str
    model: str
    read_count: int
    lines: tuple[int, ...]


class ModelHotspot(IR):
    """Aggregate access count for one model across the whole graph."""

    model: str
    total: int
    reads: int
    writes: int
    deletes: int
    accessing_functions: int


class MixedOperation(IR):
    """A function performs >1 distinct ORM operation kind (read/write/delete)."""

    qname: str
    operations: tuple[OrmOp, ...]
    models: tuple[str, ...]


class AsyncBoundaryCrossing(IR):
    """A function touches the DB *and* emits an async dispatch. The dispatch
    may execute outside the surrounding DB transaction."""

    qname: str
    orm_count: int
    async_dispatch_count: int
    models: tuple[str, ...]
    dispatches: tuple[str, ...]  # AsyncKind tags


def iter_orm_by_function(
    graph: AnalyzedGraph,
) -> Iterator[tuple[str, tuple[OrmOperationLabel, ...]]]:
    """Yield (qname, tuple of OrmOperationLabels) for every function that has
    at least one ORM label. Callers that need all functions should iterate
    `graph.annotated.resolved.functions` directly."""
    for qname, labels in graph.annotated.labels.items():
        orm = tuple(lbl for lbl in labels if isinstance(lbl, OrmOperationLabel))
        if orm:
            yield qname, orm


def find_n_plus_one(graph: AnalyzedGraph) -> Iterator[NPlusOneCandidate]:
    """Per-function: same (operation=read, model=M) appearing >=2 times.

    Two reads on the same model within one function is rarely done
    intentionally at the Python level — it's almost always a query-in-a-loop
    pattern (the loop lives at the AST layer we don't track, so we infer
    from the repeat-call signal).
    """
    for qname, orm_labels in iter_orm_by_function(graph):
        by_model: dict[str, list[int]] = defaultdict(list)
        for lbl in orm_labels:
            if lbl.operation == "read":
                by_model[lbl.model].append(lbl.line)
        for model, lines in by_model.items():
            if len(lines) >= 2:
                yield NPlusOneCandidate(
                    qname=qname,
                    model=model,
                    read_count=len(lines),
                    lines=tuple(sorted(lines)),
                )


def find_model_hotspots(graph: AnalyzedGraph) -> Iterator[ModelHotspot]:
    """Per-model totals across the entire graph, sorted most-accessed-first."""
    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"reads": 0, "writes": 0, "deletes": 0}
    )
    accessors: dict[str, set[str]] = defaultdict(set)
    for qname, orm_labels in iter_orm_by_function(graph):
        for lbl in orm_labels:
            counts[lbl.model][f"{lbl.operation}s"] += 1
            accessors[lbl.model].add(qname)

    hotspots = [
        ModelHotspot(
            model=model,
            total=c["reads"] + c["writes"] + c["deletes"],
            reads=c["reads"],
            writes=c["writes"],
            deletes=c["deletes"],
            accessing_functions=len(accessors[model]),
        )
        for model, c in counts.items()
    ]
    hotspots.sort(key=lambda h: -h.total)
    yield from hotspots


def find_mixed_operations(graph: AnalyzedGraph) -> Iterator[MixedOperation]:
    """Functions with >1 distinct ORM op kind. Suggests a larger transaction
    scope and, depending on code, a candidate for explicit transaction control."""
    for qname, orm_labels in iter_orm_by_function(graph):
        ops = {lbl.operation for lbl in orm_labels}
        if len(ops) < 2:
            continue
        models = {lbl.model for lbl in orm_labels}
        yield MixedOperation(
            qname=qname,
            operations=tuple(sorted(ops)),  # type: ignore[arg-type]
            models=tuple(sorted(models)),
        )


def find_async_boundary_crossings(
    graph: AnalyzedGraph,
) -> Iterator[AsyncBoundaryCrossing]:
    """Functions with ORM labels *and* outgoing async_kind edges.

    Classic footgun: `obj.save(); task.delay()` outside an atomic block —
    the task may run before the transaction commits (or after it aborts),
    seeing a state the caller didn't commit.
    """
    resolved = graph.annotated.resolved
    for qname, orm_labels in iter_orm_by_function(graph):
        if not orm_labels:
            continue
        async_edges = [
            e for e in resolved.get_callees(qname) if e.async_kind is not None
        ]
        if not async_edges:
            continue
        yield AsyncBoundaryCrossing(
            qname=qname,
            orm_count=len(orm_labels),
            async_dispatch_count=len(async_edges),
            models=tuple(sorted({lbl.model for lbl in orm_labels})),
            dispatches=tuple(
                sorted({e.async_kind for e in async_edges if e.async_kind})
            ),
        )
