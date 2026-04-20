"""Test-edge coverage analysis — reachability from the test tree."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from cartograph.v2.analyses import FunctionCoverage, find_coverage
from cartograph.v2.analyses._coverage import _is_test_module
from cartograph.v2.cli import main
from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.annotated import AnnotatedGraph
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
    functions: dict[str, FunctionRef],
    edges: tuple[Edge, ...] = (),
) -> AnalyzedGraph:
    resolved = ResolvedGraph(functions=functions, edges=edges)
    return AnalyzedGraph(
        annotated=AnnotatedGraph(resolved=resolved, labels={}),
        entry_points=(),
    )


class TestIsTestModule:
    def test_tests_package(self):
        assert _is_test_module("tests")
        assert _is_test_module("tests.test_thing")
        assert _is_test_module("tests.sub.more")

    def test_top_level_test_file(self):
        assert _is_test_module("test_foo")
        assert _is_test_module("test_cli")

    def test_nested_test_file(self):
        assert _is_test_module("pkg.test_foo")
        assert _is_test_module("pkg.sub.test_bar")

    def test_underscore_test_suffix(self):
        assert _is_test_module("foo_test")
        assert _is_test_module("pkg.foo_test")
        assert _is_test_module("pkg.foo_test.helpers")

    def test_multiple_test_trees(self):
        assert _is_test_module("tests_v2")
        assert _is_test_module("tests_v2.test_cache")
        assert _is_test_module("tests_integration")

    def test_non_test_modules(self):
        assert not _is_test_module("pkg.service")
        assert not _is_test_module("pkg.models")
        assert not _is_test_module("app")

    def test_testing_prefix_does_not_match(self):
        # Segment match, not prefix — `testing` utility modules aren't tests.
        assert not _is_test_module("testing")
        assert not _is_test_module("testing.utils")
        assert not _is_test_module("mypackage.testing")

    def test_contest_is_not_test(self):
        assert not _is_test_module("contest")
        assert not _is_test_module("pkg.contest")


class TestFindCoverage:
    def test_direct_call_from_test(self):
        g = _graph(
            functions={
                "app.foo": _fn("app.foo"),
                "tests.test_foo.test_ok": _fn("tests.test_foo.test_ok"),
            },
            edges=(
                Edge(
                    caller_qname="tests.test_foo.test_ok",
                    callee_qname="app.foo",
                    line=1,
                ),
            ),
        )
        rows = list(find_coverage(g))
        assert rows == [FunctionCoverage(qname="app.foo", has_test_coverage=True)]

    def test_transitive_coverage(self):
        g = _graph(
            functions={
                "app.a": _fn("app.a"),
                "app.b": _fn("app.b"),
                "app.c": _fn("app.c"),
                "tests.test_a.test_chain": _fn("tests.test_a.test_chain"),
            },
            edges=(
                Edge(
                    caller_qname="tests.test_a.test_chain",
                    callee_qname="app.a",
                    line=1,
                ),
                Edge(caller_qname="app.a", callee_qname="app.b", line=2),
                Edge(caller_qname="app.b", callee_qname="app.c", line=3),
            ),
        )
        rows = {r.qname: r.has_test_coverage for r in find_coverage(g)}
        assert rows == {"app.a": True, "app.b": True, "app.c": True}

    def test_unreachable_function_is_uncovered(self):
        g = _graph(
            functions={
                "app.used": _fn("app.used"),
                "app.unused": _fn("app.unused"),
                "tests.test_x.test_used": _fn("tests.test_x.test_used"),
            },
            edges=(
                Edge(
                    caller_qname="tests.test_x.test_used",
                    callee_qname="app.used",
                    line=1,
                ),
            ),
        )
        rows = {r.qname: r.has_test_coverage for r in find_coverage(g)}
        assert rows == {"app.used": True, "app.unused": False}

    def test_test_functions_excluded_from_output(self):
        g = _graph(
            functions={
                "app.foo": _fn("app.foo"),
                "tests.test_foo.test_ok": _fn("tests.test_foo.test_ok"),
                "tests.conftest.make_user": _fn("tests.conftest.make_user"),
            },
            edges=(
                Edge(
                    caller_qname="tests.test_foo.test_ok",
                    callee_qname="app.foo",
                    line=1,
                ),
            ),
        )
        qnames = [r.qname for r in find_coverage(g)]
        assert qnames == ["app.foo"]

    def test_output_sorted_by_qname(self):
        g = _graph(
            functions={
                "app.z": _fn("app.z"),
                "app.a": _fn("app.a"),
                "app.m": _fn("app.m"),
            },
        )
        qnames = [r.qname for r in find_coverage(g)]
        assert qnames == ["app.a", "app.m", "app.z"]

    def test_no_tests_means_everything_uncovered(self):
        g = _graph(
            functions={
                "app.a": _fn("app.a"),
                "app.b": _fn("app.b"),
            },
            edges=(Edge(caller_qname="app.a", callee_qname="app.b", line=1),),
        )
        rows = {r.qname: r.has_test_coverage for r in find_coverage(g)}
        assert rows == {"app.a": False, "app.b": False}

    def test_call_from_non_test_doesnt_confer_coverage(self):
        g = _graph(
            functions={
                "app.a": _fn("app.a"),
                "app.b": _fn("app.b"),
            },
            edges=(Edge(caller_qname="app.a", callee_qname="app.b", line=1),),
        )
        rows = {r.qname: r.has_test_coverage for r in find_coverage(g)}
        assert rows == {"app.a": False, "app.b": False}

    def test_cycle_terminates(self):
        g = _graph(
            functions={
                "app.a": _fn("app.a"),
                "app.b": _fn("app.b"),
                "tests.test_c.test_kick": _fn("tests.test_c.test_kick"),
            },
            edges=(
                Edge(
                    caller_qname="tests.test_c.test_kick",
                    callee_qname="app.a",
                    line=1,
                ),
                Edge(caller_qname="app.a", callee_qname="app.b", line=2),
                Edge(caller_qname="app.b", callee_qname="app.a", line=3),
            ),
        )
        rows = {r.qname: r.has_test_coverage for r in find_coverage(g)}
        assert rows == {"app.a": True, "app.b": True}

    def test_alternative_test_tree_names(self):
        g = _graph(
            functions={
                "app.one": _fn("app.one"),
                "app.two": _fn("app.two"),
                "tests_v2.test_one.test_it": _fn("tests_v2.test_one.test_it"),
                "app.two_test.test_it": _fn("app.two_test.test_it"),
            },
            edges=(
                Edge(
                    caller_qname="tests_v2.test_one.test_it",
                    callee_qname="app.one",
                    line=1,
                ),
                Edge(
                    caller_qname="app.two_test.test_it",
                    callee_qname="app.two",
                    line=1,
                ),
            ),
        )
        rows = {r.qname: r.has_test_coverage for r in find_coverage(g)}
        assert rows == {"app.one": True, "app.two": True}


class TestCoverageCli:
    def test_coverage_help_lists_show_option(self):
        runner = CliRunner()
        result = runner.invoke(main, ["coverage", "--help"])
        assert result.exit_code == 0
        assert "--show" in result.output
        assert "uncovered" in result.output

    def test_coverage_listed_in_main_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "coverage" in result.output


# ──────────────────────────────────────────────────────────────────────────────
# Real-ty integration — src + tests in a tmpdir, run the pipeline, assert shape
@pytest.mark.integration
class TestCoverageRealTy:
    """End-to-end with real `ty`. Skipped when the binary isn't on PATH."""

    @pytest.fixture
    def ty_available(self):
        import shutil as _shutil

        if _shutil.which("ty") is None:
            pytest.skip("ty binary not on PATH")
        return True

    def _build_with_tests(self, project_root: Path):
        import asyncio

        from cartograph.v2.config import RunConfig
        from cartograph.v2.pipeline import Pipeline
        from cartograph.v2.stages.annotate.registry import default_annotators
        from cartograph.v2.stages.discover.topology import TopologyDiscoverer
        from cartograph.v2.stages.extract.treesitter_extractor import (
            TreesitterExtractor,
        )
        from cartograph.v2.stages.present.cli import CliPresenter
        from cartograph.v2.stages.resolve.lsp.server import LspServer
        from cartograph.v2.stages.resolve.ty_resolver import TyResolver

        async def run():
            async with LspServer(["ty", "server"]) as server:
                pipeline = Pipeline(
                    extractor=TreesitterExtractor(),
                    resolver=TyResolver(server=server),
                    annotators=default_annotators(),
                    discoverer=TopologyDiscoverer(),
                    presenter=CliPresenter(),
                )
                return await pipeline.build(
                    RunConfig(project_root=project_root, include_tests=True)
                )

        return asyncio.run(run())

    def test_coverage_pipeline_shape_with_real_ty(self, ty_available, tmp_path):
        # Cross-module resolution is flaky in hermetic tmpdirs without a
        # pyproject; reachability itself is covered by the unit tests above.
        # This one asserts IR shape + test-module exclusion only.
        (tmp_path / "app.py").write_text(
            "def used():\n    return 1\n\ndef unused():\n    return 2\n"
        )
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "__init__.py").write_text("")
        (tmp_path / "tests" / "test_app.py").write_text(
            "from app import used\n\ndef test_used():\n    assert used() == 1\n"
        )

        built = self._build_with_tests(tmp_path)
        from cartograph.v2.ir.base import is_ok

        assert is_ok(built), built
        graph = built.value

        all_qnames = set(graph.annotated.resolved.functions)
        assert any(q.startswith("tests.") for q in all_qnames)

        rows = list(find_coverage(graph))
        qnames = [r.qname for r in rows]
        assert any(q.endswith(".used") for q in qnames)
        assert any(q.endswith(".unused") for q in qnames)
        assert not any(q.startswith("tests.") for q in qnames)
        assert qnames == sorted(qnames)
        for row in rows:
            assert isinstance(row, FunctionCoverage)
            assert isinstance(row.has_test_coverage, bool)
