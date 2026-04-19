"""CommonGraph IR."""

from __future__ import annotations

from cartograph.v2.ir.common import (
    CommonEdge,
    CommonEntryPoint,
    CommonFunction,
    CommonGraph,
)


def _build_graph() -> CommonGraph:
    return CommonGraph(
        project_name="demo",
        producer="v2-ty",
        functions={
            "a.f": CommonFunction(qname="a.f", module="a", name="f", line=1),
            "b.g": CommonFunction(qname="b.g", module="b", name="g", line=10),
        },
        edges=(
            CommonEdge(caller="a.f", callee="b.g", line=5),
            CommonEdge(caller="a.f", callee="b.g", line=7),  # duplicate pair
        ),
        entry_points=(
            CommonEntryPoint(qname="a.f", kind="discovered", trigger="@main.command"),
        ),
    )


class TestCommonGraph:
    def test_construction(self):
        g = _build_graph()
        assert g.producer == "v2-ty"
        assert len(g.edges) == 2

    def test_edge_set_deduplicates_by_pair(self):
        g = _build_graph()
        assert g.edge_set == frozenset({("a.f", "b.g")})

    def test_entry_qnames(self):
        g = _build_graph()
        assert g.entry_qnames == frozenset({"a.f"})

    def test_empty_graph_edge_set(self):
        g = CommonGraph(project_name="x", producer="v1")
        assert g.edge_set == frozenset()
        assert g.entry_qnames == frozenset()

    def test_json_roundtrip(self):
        g = _build_graph()
        dumped = g.model_dump_json()
        restored = CommonGraph.model_validate_json(dumped)
        assert restored == g
