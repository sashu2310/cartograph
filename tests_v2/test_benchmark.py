"""Benchmark harness tests — adapters, metrics, runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from cartograph.v2.benchmark.adapters.v2_to_common import v2_to_common
from cartograph.v2.benchmark.metrics import (
    BenchmarkResult,
    compare,
    format_report,
)
from cartograph.v2.benchmark.runner import run_target, run_v1
from cartograph.v2.ir.analyzed import (
    AnalyzedGraph,
    ApiRouteEntry,
    CeleryTaskEntry,
    DiscoveredEntry,
)
from cartograph.v2.ir.annotated import AnnotatedGraph
from cartograph.v2.ir.common import (
    CommonEdge,
    CommonEntryPoint,
    CommonGraph,
)
from cartograph.v2.ir.resolved import Edge, FunctionRef, ResolvedGraph

# ──────────────────────────────────────────────────────────────────────────────
# v2_to_common adapter
# ──────────────────────────────────────────────────────────────────────────────


def _fn(qname: str, path: str = "/tmp/x.py") -> FunctionRef:
    module, _, name = qname.rpartition(".")
    return FunctionRef(
        qname=qname,
        name=name,
        module=module,
        line_start=1,
        line_end=5,
        source_path=Path(path),
    )


def _build_analyzed() -> AnalyzedGraph:
    resolved = ResolvedGraph(
        functions={
            "app.root": _fn("app.root"),
            "app.leaf": _fn("app.leaf"),
        },
        edges=(Edge(caller_qname="app.root", callee_qname="app.leaf", line=1),),
    )
    return AnalyzedGraph(
        annotated=AnnotatedGraph(resolved=resolved),
        entry_points=(
            DiscoveredEntry(qname="app.root", trigger_decorator="main.command"),
        ),
    )


class TestV2ToCommon:
    def test_basic_conversion(self):
        common = v2_to_common(
            _build_analyzed(),
            project_name="demo",
            producer="v2-ty",
            project_commit="abc123",
        )
        assert common.producer == "v2-ty"
        assert common.project_name == "demo"
        assert common.project_commit == "abc123"
        assert set(common.functions) == {"app.root", "app.leaf"}
        assert len(common.edges) == 1
        assert common.edges[0].caller == "app.root"
        assert common.edges[0].callee == "app.leaf"

    def test_entry_point_kinds_preserved(self):
        analyzed = AnalyzedGraph(
            annotated=AnnotatedGraph(resolved=ResolvedGraph(functions={}, edges=())),
            entry_points=(
                DiscoveredEntry(qname="a.cli", trigger_decorator="main.command"),
                ApiRouteEntry(qname="b.view", method="GET", path="/x"),
                CeleryTaskEntry(qname="c.task", queue="default"),
            ),
        )
        common = v2_to_common(analyzed, project_name="demo")
        kinds = {ep.kind for ep in common.entry_points}
        assert kinds == {"discovered", "api_route", "celery_task"}

    def test_entry_point_triggers_formatted(self):
        analyzed = AnalyzedGraph(
            annotated=AnnotatedGraph(resolved=ResolvedGraph(functions={}, edges=())),
            entry_points=(
                DiscoveredEntry(qname="a.cli", trigger_decorator="main.command"),
                ApiRouteEntry(qname="b.view", method="POST", path="/users"),
                CeleryTaskEntry(qname="c.task", queue="priority"),
            ),
        )
        common = v2_to_common(analyzed, project_name="demo")
        triggers = {ep.qname: ep.trigger for ep in common.entry_points}
        assert triggers["a.cli"] == "@main.command"
        assert triggers["b.view"] == "POST /users"
        assert triggers["c.task"] == "celery_task[priority]"


# ──────────────────────────────────────────────────────────────────────────────
# metrics.compare
# ──────────────────────────────────────────────────────────────────────────────


def _result(
    producer: str, edges: tuple[CommonEdge, ...], entries: tuple = ()
) -> BenchmarkResult:
    graph = CommonGraph(
        project_name="demo",
        producer=producer,
        functions={},
        edges=edges,
        entry_points=entries,
    )
    return BenchmarkResult(
        target="v1" if producer == "v1" else "v2-ty",
        project_name="demo",
        version=producer,
        total_call_sites=len(edges),
        resolved_count=len(edges),
        unresolved_count=0,
        wall_time_s=1.0,
        peak_memory_mb=10.0,
        graph=graph,
    )


class TestCompare:
    def test_perfect_agreement(self):
        edges = (CommonEdge(caller="a", callee="b", line=1),)
        a = _result("v1", edges)
        b = _result("v2-ty", edges)
        r = compare(a, b)
        assert r.shared_edges == 1
        assert r.only_a == 0
        assert r.only_b == 0
        assert r.jaccard == 1.0
        assert r.a_corroborated_by_b == 1.0
        assert r.b_corroborated_by_a == 1.0

    def test_partial_overlap(self):
        a_edges = (
            CommonEdge(caller="a", callee="b", line=1),
            CommonEdge(caller="a", callee="c", line=2),
        )
        b_edges = (CommonEdge(caller="a", callee="b", line=1),)
        r = compare(_result("v1", a_edges), _result("v2-ty", b_edges))
        assert r.shared_edges == 1
        assert r.only_a == 1
        assert r.only_b == 0
        assert r.jaccard == pytest.approx(0.5)
        # Half of A's edges are in B; all of B's edges are in A.
        assert r.a_corroborated_by_b == 0.5
        assert r.b_corroborated_by_a == 1.0

    def test_disjoint_graphs(self):
        a_edges = (CommonEdge(caller="a", callee="b", line=1),)
        b_edges = (CommonEdge(caller="x", callee="y", line=1),)
        r = compare(_result("v1", a_edges), _result("v2-ty", b_edges))
        assert r.shared_edges == 0
        assert r.only_a == 1
        assert r.only_b == 1
        assert r.jaccard == 0.0

    def test_empty_graphs(self):
        r = compare(_result("v1", ()), _result("v2-ty", ()))
        assert r.jaccard == 0.0
        assert r.a_corroborated_by_b == 0.0
        assert r.b_corroborated_by_a == 0.0

    def test_jaccard_symmetric_under_swap(self):
        a_edges = (CommonEdge(caller="a", callee="b", line=1),)
        b_edges = (
            CommonEdge(caller="a", callee="b", line=1),
            CommonEdge(caller="a", callee="c", line=2),
        )
        r_ab = compare(_result("v1", a_edges), _result("v2-ty", b_edges))
        r_ba = compare(_result("v2-ty", b_edges), _result("v1", a_edges))
        assert r_ab.jaccard == r_ba.jaccard
        # But per-target corroboration is asymmetric.
        assert r_ab.a_corroborated_by_b == r_ba.b_corroborated_by_a

    def test_shared_entry_points_counted(self):
        a = _result(
            "v1",
            (),
            entries=(
                CommonEntryPoint(qname="a.f", kind="discovered"),
                CommonEntryPoint(qname="b.g", kind="discovered"),
            ),
        )
        b = _result(
            "v2-ty",
            (),
            entries=(
                CommonEntryPoint(qname="a.f", kind="discovered"),
                CommonEntryPoint(qname="c.h", kind="discovered"),
            ),
        )
        r = compare(a, b)
        assert r.shared_entry_points == 1

    def test_format_report_uses_neutral_terms(self):
        edges = (CommonEdge(caller="a", callee="b", line=1),)
        r = compare(_result("v1", edges), _result("v2-ty", edges))
        text = format_report(r)
        # No accuracy-style claims.
        assert "precision" not in text.lower()
        assert "recall" not in text.lower()
        assert "f1" not in text.lower()
        assert "accuracy" not in text.lower()
        # Descriptive terms only.
        assert "jaccard" in text
        assert "corroborated" in text


# ──────────────────────────────────────────────────────────────────────────────
# runner.run_v1 integration — uses a tmp project
# ──────────────────────────────────────────────────────────────────────────────


class TestRunV1:
    def test_produces_valid_result(self, tmp_path):
        (tmp_path / "app.py").write_text(
            "def helper():\n    return 1\n\ndef driver():\n    return helper()\n"
        )
        result = run_v1(tmp_path, project_name="demo")
        assert result.target == "v1"
        assert result.project_name == "demo"
        assert result.wall_time_s > 0
        assert result.graph.producer == "v1"
        # Driver calls helper — should show up.
        callers = {e.caller for e in result.graph.edges}
        assert "app.driver" in callers


# ──────────────────────────────────────────────────────────────────────────────
# Real-ty integration — v1 vs v2-ty on a tmp project
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestBenchmarkIntegration:
    @pytest.mark.asyncio
    async def test_v1_vs_v2_ty_on_simple_project(self, tmp_path):
        """First real comparison. Tiny project, both targets resolve the
        driver → helper edge."""
        import shutil

        if shutil.which("ty") is None:
            pytest.skip("ty binary not on PATH")

        (tmp_path / "app.py").write_text(
            "def helper():\n    return 1\n\ndef driver():\n    return helper()\n"
        )

        v1_res = await run_target("v1", tmp_path, project_name="demo")
        v2_res = await run_target("v2-ty", tmp_path, project_name="demo")

        report = compare(v1_res, v2_res)
        # Both should find the one real edge.
        assert report.shared_edges >= 1, (
            f"expected at least 1 shared edge; got\n{format_report(report)}"
        )
