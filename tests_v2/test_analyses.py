"""Analyses — pure functions over AnalyzedGraph."""

from __future__ import annotations

from pathlib import Path

from cartograph.v2.analyses import (
    AnalysisReport,
    analyze,
    diff_graphs,
    find_async_boundary_crossings,
    find_mixed_operations,
    find_model_hotspots,
    find_n_plus_one,
)
from cartograph.v2.ir.analyzed import (
    AnalyzedGraph,
    ApiRouteEntry,
    CeleryTaskEntry,
    DiscoveredEntry,
)
from cartograph.v2.ir.annotated import (
    AnnotatedGraph,
    ApiRouteLabel,
    CeleryTaskLabel,
    OrmOperationLabel,
)
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


class TestGraphDiff:
    def _with_entries(
        self, functions, edges=(), labels=None, entries=()
    ) -> AnalyzedGraph:
        resolved = ResolvedGraph(functions=functions, edges=edges)
        return AnalyzedGraph(
            annotated=AnnotatedGraph(resolved=resolved, labels=labels or {}),
            entry_points=entries,
        )

    def test_identical_graphs_produce_empty_diff(self):
        g = self._with_entries(
            functions={"a.f": _fn("a.f"), "a.g": _fn("a.g")},
            edges=(Edge(caller_qname="a.f", callee_qname="a.g", line=1),),
        )
        diff = diff_graphs(g, g, from_sha="a" * 40, to_sha="b" * 40)
        assert diff.is_empty
        assert diff.added_edges == ()
        assert diff.removed_edges == ()
        assert diff.from_sha == "a" * 40
        assert diff.to_sha == "b" * 40

    def test_added_edge_shows_up_on_the_right_side(self):
        from_g = self._with_entries(functions={"a.f": _fn("a.f"), "a.g": _fn("a.g")})
        to_g = self._with_entries(
            functions={"a.f": _fn("a.f"), "a.g": _fn("a.g")},
            edges=(Edge(caller_qname="a.f", callee_qname="a.g", line=3),),
        )
        diff = diff_graphs(from_g, to_g, from_sha="x", to_sha="y")
        assert len(diff.added_edges) == 1
        assert diff.added_edges[0].caller_qname == "a.f"
        assert diff.added_edges[0].callee_qname == "a.g"
        assert diff.added_edges[0].line == 3
        assert diff.removed_edges == ()

    def test_removed_edge_shows_up_on_the_left_side(self):
        from_g = self._with_entries(
            functions={"a.f": _fn("a.f"), "a.g": _fn("a.g")},
            edges=(Edge(caller_qname="a.f", callee_qname="a.g", line=5),),
        )
        to_g = self._with_entries(functions={"a.f": _fn("a.f"), "a.g": _fn("a.g")})
        diff = diff_graphs(from_g, to_g, from_sha="x", to_sha="y")
        assert len(diff.removed_edges) == 1
        assert diff.removed_edges[0].line == 5
        assert diff.added_edges == ()

    def test_same_edge_different_async_kind_is_remove_plus_add(self):
        # `foo()` → `foo.delay()` is a semantic change, so the diff renders
        # it as remove+add rather than collapsing by (caller, callee, line).
        base = {"a.f": _fn("a.f"), "a.g": _fn("a.g")}
        from_g = self._with_entries(
            functions=base,
            edges=(Edge(caller_qname="a.f", callee_qname="a.g", line=2),),
        )
        to_g = self._with_entries(
            functions=base,
            edges=(
                Edge(
                    caller_qname="a.f",
                    callee_qname="a.g",
                    line=2,
                    async_kind="celery_delay",
                ),
            ),
        )
        diff = diff_graphs(from_g, to_g, from_sha="x", to_sha="y")
        assert len(diff.removed_edges) == 1
        assert len(diff.added_edges) == 1
        assert diff.removed_edges[0].async_kind is None
        assert diff.added_edges[0].async_kind == "celery_delay"

    def test_added_and_removed_functions(self):
        from_g = self._with_entries(
            functions={"a.keep": _fn("a.keep"), "a.gone": _fn("a.gone")},
        )
        to_g = self._with_entries(
            functions={"a.keep": _fn("a.keep"), "a.fresh": _fn("a.fresh")},
        )
        diff = diff_graphs(from_g, to_g, from_sha="x", to_sha="y")
        assert tuple(f.qname for f in diff.added_functions) == ("a.fresh",)
        assert tuple(f.qname for f in diff.removed_functions) == ("a.gone",)

    def test_entry_point_added_removed_and_kind_changed(self):
        fns = {"a.hello": _fn("a.hello"), "a.task": _fn("a.task")}
        from_g = self._with_entries(
            functions=fns,
            entries=(
                ApiRouteEntry(qname="a.hello", method="GET", path="/hello"),
                CeleryTaskEntry(qname="a.task"),
            ),
        )
        to_g = self._with_entries(
            functions={**fns, "a.newroute": _fn("a.newroute")},
            entries=(
                DiscoveredEntry(qname="a.hello", trigger_decorator="custom"),
                ApiRouteEntry(qname="a.newroute", method="POST", path="/new"),
            ),
        )
        diff = diff_graphs(from_g, to_g, from_sha="x", to_sha="y")
        assert diff.added_entries == ("a.newroute",)
        assert diff.removed_entries == ("a.task",)
        assert len(diff.entry_kind_changes) == 1
        kc = diff.entry_kind_changes[0]
        assert kc.qname == "a.hello"
        assert kc.from_kind == "api_route"
        assert kc.to_kind == "discovered"

    def test_label_diff_uses_full_json_payload(self):
        # GET → POST on the same route surfaces as remove+add because labels
        # are compared by full JSON, not just the discriminator.
        fns = {"a.hello": _fn("a.hello")}
        from_g = self._with_entries(
            functions=fns,
            labels={
                "a.hello": (
                    ApiRouteLabel(framework="fastapi", method="GET", path="/hello"),
                )
            },
        )
        to_g = self._with_entries(
            functions=fns,
            labels={
                "a.hello": (
                    ApiRouteLabel(framework="fastapi", method="POST", path="/hello"),
                )
            },
        )
        diff = diff_graphs(from_g, to_g, from_sha="x", to_sha="y")
        assert len(diff.added_labels) == 1
        assert len(diff.removed_labels) == 1
        assert '"method":"GET"' in diff.removed_labels[0].label_json
        assert '"method":"POST"' in diff.added_labels[0].label_json

    def test_label_added_on_a_qname_that_had_none(self):
        fns = {"a.hello": _fn("a.hello")}
        from_g = self._with_entries(functions=fns, labels={})
        to_g = self._with_entries(
            functions=fns,
            labels={"a.hello": (CeleryTaskLabel(queue="default"),)},
        )
        diff = diff_graphs(from_g, to_g, from_sha="x", to_sha="y")
        assert len(diff.added_labels) == 1
        assert diff.added_labels[0].label_kind == "celery_task"
        assert diff.removed_labels == ()

    def test_output_is_deterministic(self):
        fns = {
            "a.f": _fn("a.f"),
            "a.g": _fn("a.g"),
            "a.h": _fn("a.h"),
        }
        from_g = self._with_entries(
            functions={"a.f": fns["a.f"], "a.g": fns["a.g"]},
            edges=(Edge(caller_qname="a.f", callee_qname="a.g", line=1),),
        )
        to_g = self._with_entries(
            functions={"a.f": fns["a.f"], "a.h": fns["a.h"]},
            edges=(
                Edge(caller_qname="a.f", callee_qname="a.h", line=4),
                Edge(caller_qname="a.f", callee_qname="a.h", line=5),
            ),
        )
        d1 = diff_graphs(from_g, to_g, from_sha="x", to_sha="y")
        d2 = diff_graphs(from_g, to_g, from_sha="x", to_sha="y")
        assert d1.model_dump_json() == d2.model_dump_json()

    def test_is_empty_flag(self):
        g = self._with_entries(functions={"a.f": _fn("a.f")})
        d = diff_graphs(g, g, from_sha="x", to_sha="y")
        assert d.is_empty is True

        other = self._with_entries(functions={"a.f": _fn("a.f"), "a.new": _fn("a.new")})
        d = diff_graphs(g, other, from_sha="x", to_sha="y")
        assert d.is_empty is False
