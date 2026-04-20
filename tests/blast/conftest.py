"""Shared fixtures for blast radius tests."""

from pathlib import Path

import pytest

from cartograph.config import CartographConfig
from cartograph.core import parse_project
from cartograph.graph.call_graph import CallGraphBuilder

BLAST_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "blast"


@pytest.fixture
def blast_fixtures_dir():
    return BLAST_FIXTURES_DIR


@pytest.fixture
def sample_project_index_and_graph():
    """Build a real ProjectIndex + CallGraph from tests/fixtures/blast/sample_project/."""
    project_dir = (BLAST_FIXTURES_DIR / "sample_project").resolve()
    config = CartographConfig(root_path=str(project_dir), include_tests=True)
    config.exclude_dirs.discard("tests")
    config.exclude_dirs.discard("test")
    index = parse_project(config)
    graph = CallGraphBuilder(index).build()
    return index, graph


@pytest.fixture
def sample_test_index(sample_project_index_and_graph):
    """Build a TestIndex from tests/fixtures/blast/sample_tests/."""
    from cartograph.blast.tests_index import build_test_index

    index, _ = sample_project_index_and_graph
    test_dir = BLAST_FIXTURES_DIR / "sample_tests"
    return build_test_index(index, test_dir)
