"""v1 scan → v1_to_common → CommonGraph integration check."""

from __future__ import annotations

from pathlib import Path

import pytest

from cartograph.config import CartographConfig
from cartograph.core import parse_and_build
from cartograph.v2.benchmark.adapters.v1_to_common import v1_to_common
from cartograph.v2.ir.common import CommonGraph


@pytest.fixture(scope="module")
def v1_scan():
    """Run v1 on the cartograph/ package (this repo's own source)."""
    root = Path(__file__).resolve().parents[1] / "cartograph"
    config = CartographConfig(root_path=str(root))
    return parse_and_build(config, use_cache=False)


@pytest.fixture(scope="module")
def common(v1_scan) -> CommonGraph:
    index, graph = v1_scan
    return v1_to_common(
        index,
        graph,
        project_name="cartograph",
        project_commit="HEAD",
    )


def test_producer_is_v1(common: CommonGraph):
    assert common.producer == "v1"


def test_project_metadata(common: CommonGraph):
    assert common.project_name == "cartograph"
    assert common.project_commit == "HEAD"


def test_has_functions(common: CommonGraph):
    assert len(common.functions) > 0


def test_has_edges(common: CommonGraph):
    assert len(common.edges) > 0


def test_has_entry_points(common: CommonGraph):
    assert len(common.entry_points) > 0


def test_function_count_matches_v1(v1_scan, common: CommonGraph):
    index, _ = v1_scan
    v1_func_count = sum(len(m.functions) for m in index.modules.values())
    assert len(common.functions) == v1_func_count


def test_edge_count_matches_v1(v1_scan, common: CommonGraph):
    _, graph = v1_scan
    assert len(common.edges) == len(graph.edges)


def test_entry_point_count_matches_v1(v1_scan, common: CommonGraph):
    index, _ = v1_scan
    assert len(common.entry_points) == len(index.entry_points)


def test_all_edges_reference_known_functions_or_are_external(common: CommonGraph):
    """Every edge's caller should be a known function. The callee may be external
    (e.g., a framework function), which is normal. Just sanity-check caller side."""
    for edge in common.edges:
        assert edge.caller in common.functions


def test_edge_set_usable_for_comparison(common: CommonGraph):
    es = common.edge_set
    assert isinstance(es, frozenset)
    if common.edges:
        sample = common.edges[0]
        assert (sample.caller, sample.callee) in es


def test_cli_scan_is_entry_point(common: CommonGraph):
    """Cartograph's own CLI commands should surface as entry points.
    Sanity check that topology discovery is wiring through the adapter.

    Note: v1 qnames are relative to the scan root, so scanning the
    `cartograph/` package gives qnames like `cli.scan`, not `cartograph.cli.scan`.
    """
    assert "cli.scan" in common.entry_qnames
