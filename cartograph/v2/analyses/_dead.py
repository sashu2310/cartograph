"""Dead code detection — functions/classes with zero incoming edges."""

from __future__ import annotations

from collections.abc import Iterator

from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.base import IR


class DeadFunction(IR):
    """A function or class with zero incoming edges, not an entry point.

    Confidence is heuristic — dynamic dispatch (getattr, string-indexed
    dicts of callables, __getattr__) can bypass the static graph, so a
    reported dead function may actually be reachable at runtime. Treat the
    report as a starting list for review, not a deletion list.
    """

    qname: str
    kind: str  # "function" | "method" | "class"
    source_path: str
    line_start: int


def find_dead(graph: AnalyzedGraph) -> Iterator[DeadFunction]:
    """Functions/classes with zero incoming edges and no entry-point status.

    Excluded on purpose:
        - Functions/classes named `__init__`, `__main__`, `main` — often
          imported-and-invoked from outside the graph we can see.
        - Dunder methods (`__init__`, `__enter__`, `__aexit__`, etc.) —
          called implicitly by Python semantics, not by static callers.
        - Classes whose methods have callers — if a method of `Foo` is
          reached, `Foo` itself clearly has a reason to exist even if
          never syntactically constructed.
    """
    resolved = graph.annotated.resolved
    entry_qnames = {ep.qname for ep in graph.entry_points}

    # Methods on a "live" class — we consider the class reachable if *any*
    # of its methods has callers.
    live_classes: set[str] = set()
    for qname, fn in resolved.functions.items():
        if (
            fn.kind == "method"
            and fn.class_name
            and resolved.callers_by_callee.get(qname)
        ):
            live_classes.add(f"{fn.module}.{fn.class_name}")

    for qname, fn in resolved.functions.items():
        if qname in entry_qnames:
            continue
        if resolved.callers_by_callee.get(qname):
            continue
        name = fn.name
        if name.startswith("__") and name.endswith("__"):
            continue
        if name in {"main", "__main__"}:
            continue
        if fn.kind == "class" and qname in live_classes:
            continue
        yield DeadFunction(
            qname=qname,
            kind=fn.kind,
            source_path=str(fn.source_path),
            line_start=fn.line_start,
        )
