"""Analyses — pure functions over AnalyzedGraph."""

from __future__ import annotations

from pathlib import Path

from cartograph.v2.analyses import (
    AnalysisReport,
    analyze,
    find_async_boundary_crossings,
    find_mixed_operations,
    find_model_hotspots,
    find_n_plus_one,
)
from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.annotated import AnnotatedGraph, OrmOperationLabel
from cartograph.v2.ir.resolved import Edge, FunctionRef, ResolvedGraph


def _fn(qname: str) -> FunctionRef:
    module, _, name = qname.rpartition(".")
    return FunctionRef(
        qname=qname,
        name=name,
        module=module,
        line_start=1,
        line_end=20,
        source_path=Path("/tmp/x.py"),
    )


def _graph(
    *,
    functions: dict[str, FunctionRef] | None = None,
    edges: tuple[Edge, ...] = (),
    labels: dict | None = None,
) -> AnalyzedGraph:
    resolved = ResolvedGraph(functions=functions or {}, edges=edges)
    return AnalyzedGraph(
        annotated=AnnotatedGraph(resolved=resolved, labels=labels or {}),
        entry_points=(),
    )


def _orm(op, model, line) -> OrmOperationLabel:
    return OrmOperationLabel(framework="django", operation=op, model=model, line=line)


class TestNPlusOne:
    def test_three_reads_same_model_one_function(self):
        g = _graph(
            functions={"a.loop": _fn("a.loop")},
            labels={
                "a.loop": (
                    _orm("read", "User", 3),
                    _orm("read", "User", 4),
                    _orm("read", "User", 5),
                )
            },
        )
        hits = list(find_n_plus_one(g))
        assert len(hits) == 1
        assert hits[0].qname == "a.loop"
        assert hits[0].model == "User"
        assert hits[0].read_count == 3
        assert hits[0].lines == (3, 4, 5)

    def test_single_read_not_flagged(self):
        g = _graph(
            functions={"a.f": _fn("a.f")},
            labels={"a.f": (_orm("read", "User", 1),)},
        )
        assert list(find_n_plus_one(g)) == []

    def test_writes_dont_trigger_n_plus_one(self):
        # Two writes to same model are usually intentional, not N+1
        g = _graph(
            functions={"a.f": _fn("a.f")},
            labels={
                "a.f": (
                    _orm("write", "User", 1),
                    _orm("write", "User", 2),
                )
            },
        )
        assert list(find_n_plus_one(g)) == []


class TestHotspots:
    def test_aggregate_across_functions(self):
        g = _graph(
            functions={"a.f": _fn("a.f"), "a.g": _fn("a.g")},
            labels={
                "a.f": (_orm("read", "User", 1), _orm("write", "User", 2)),
                "a.g": (_orm("read", "Order", 3),),
            },
        )
        hits = list(find_model_hotspots(g))
        # Sorted by total desc: User=2, Order=1
        assert [h.model for h in hits] == ["User", "Order"]
        assert hits[0].total == 2
        assert hits[0].reads == 1
        assert hits[0].writes == 1
        assert hits[0].accessing_functions == 1  # only a.f hits User

    def test_access_function_count_unique(self):
        g = _graph(
            functions={"a.f": _fn("a.f"), "a.g": _fn("a.g")},
            labels={
                "a.f": (_orm("read", "User", 1), _orm("read", "User", 2)),
                "a.g": (_orm("read", "User", 3),),
            },
        )
        hits = list(find_model_hotspots(g))
        assert hits[0].accessing_functions == 2  # a.f and a.g both access User


class TestMixedOperations:
    def test_read_plus_write_flagged(self):
        g = _graph(
            functions={"a.f": _fn("a.f")},
            labels={
                "a.f": (
                    _orm("read", "User", 1),
                    _orm("write", "User", 2),
                )
            },
        )
        hits = list(find_mixed_operations(g))
        assert len(hits) == 1
        assert hits[0].operations == ("read", "write")

    def test_read_only_not_flagged(self):
        g = _graph(
            functions={"a.f": _fn("a.f")},
            labels={"a.f": (_orm("read", "User", 1), _orm("read", "User", 2))},
        )
        assert list(find_mixed_operations(g)) == []

    def test_all_three_ops(self):
        g = _graph(
            functions={"a.f": _fn("a.f")},
            labels={
                "a.f": (
                    _orm("read", "Order", 1),
                    _orm("write", "Order", 2),
                    _orm("delete", "Order", 3),
                )
            },
        )
        hits = list(find_mixed_operations(g))
        assert hits[0].operations == ("delete", "read", "write")


class TestAsyncBoundaryCrossing:
    def test_orm_plus_dispatch_in_same_function(self):
        g = _graph(
            functions={"a.caller": _fn("a.caller"), "a.task": _fn("a.task")},
            edges=(
                Edge(
                    caller_qname="a.caller",
                    callee_qname="a.task",
                    line=5,
                    async_kind="celery_delay",
                ),
            ),
            labels={"a.caller": (_orm("write", "User", 3),)},
        )
        hits = list(find_async_boundary_crossings(g))
        assert len(hits) == 1
        assert hits[0].qname == "a.caller"
        assert hits[0].dispatches == ("celery_delay",)
        assert hits[0].models == ("User",)

    def test_orm_without_dispatch_not_flagged(self):
        g = _graph(
            functions={"a.f": _fn("a.f")},
            labels={"a.f": (_orm("read", "User", 1),)},
        )
        assert list(find_async_boundary_crossings(g)) == []

    def test_dispatch_without_orm_not_flagged(self):
        g = _graph(
            functions={"a.f": _fn("a.f"), "a.task": _fn("a.task")},
            edges=(
                Edge(
                    caller_qname="a.f",
                    callee_qname="a.task",
                    line=5,
                    async_kind="celery_delay",
                ),
            ),
            labels={},
        )
        assert list(find_async_boundary_crossings(g)) == []


class TestAnalyzeBundle:
    def test_analyze_returns_all_four(self):
        g = _graph(
            functions={"a.loop": _fn("a.loop"), "a.task": _fn("a.task")},
            edges=(
                Edge(
                    caller_qname="a.loop",
                    callee_qname="a.task",
                    line=7,
                    async_kind="celery_delay",
                ),
            ),
            labels={
                "a.loop": (
                    _orm("read", "User", 1),
                    _orm("read", "User", 2),
                    _orm("write", "Profile", 3),
                )
            },
        )
        report = analyze(g)
        assert isinstance(report, AnalysisReport)
        assert report.n_plus_one and report.n_plus_one[0].model == "User"
        assert report.hotspots and report.hotspots[0].model == "User"
        assert report.mixed_ops and report.mixed_ops[0].qname == "a.loop"
        assert (
            report.boundary_crossings and report.boundary_crossings[0].qname == "a.loop"
        )
