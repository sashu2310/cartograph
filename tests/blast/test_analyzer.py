"""Tests for cartograph.blast.analyzer — AC-3, AC-4, AC-10, AC-11."""

import copy
from pathlib import Path

import pytest

from cartograph.blast.analyzer import BlastAnalyzer
from cartograph.blast.models import ImpactSeverity
from cartograph.graph.call_graph import CallGraph, CallGraphBuilder
from cartograph.graph.models import ProjectIndex

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
FASTAPI_FIXTURE = FIXTURES_DIR / "fastapi_app.py"


def _build_fastapi_index() -> tuple[ProjectIndex, CallGraph]:
    """Build a ProjectIndex + CallGraph from the fastapi_app.py fixture."""
    from cartograph.parser.languages.python.adapter import PythonAdapter
    from cartograph.parser.languages.python.frameworks.fastapi import FastAPIDetector
    from cartograph.parser.registry import FrameworkRegistry

    adapter = PythonAdapter()
    module_path = "fixtures.fastapi_app"
    module = adapter.parse_file(str(FASTAPI_FIXTURE), module_path)
    assert module is not None

    fw_registry = FrameworkRegistry()
    fw_registry.register("python", FastAPIDetector())

    index = ProjectIndex(root_path=str(FIXTURES_DIR))
    entry_points = fw_registry.detect_all_entry_points(module, "python")
    index.entry_points.extend(entry_points)
    fw_registry.annotate_module(module, "python")
    index.modules[module.module_path] = module

    graph = CallGraphBuilder(index).build()
    return index, graph


class TestBlastAnalyzerBfsUpstreamDownstream:
    # Spec: Section 7, Criterion #3 — "BFS finds upstream and downstream from changed fn"

    def test_downstream_found(self, sample_project_index_and_graph):
        # Spec: Section 7, Criterion #3 — "c.baz is downstream depth=1 from b.bar"
        index, graph = sample_project_index_and_graph

        # Find service.handle qname
        service_handle = next(
            (q for q in graph.functions if q.endswith(".handle")), None
        )
        assert service_handle is not None, "service.handle not found in graph"

        analyzer = BlastAnalyzer(graph=graph, index=index)
        report = analyzer.analyze_functions([service_handle])

        downstream_qnames = [
            f.qualified_name
            for f in report.affected_functions
            if f.severity == ImpactSeverity.DOWNSTREAM
        ]
        # helper.work is called by service.handle → downstream
        assert any("work" in q for q in downstream_qnames), (
            f"Expected helper.work in downstream, got: {downstream_qnames}"
        )

    def test_upstream_found(self, sample_project_index_and_graph):
        # Spec: Section 7, Criterion #3 — "a.foo is upstream depth=1 from b.bar"
        index, graph = sample_project_index_and_graph

        service_handle = next(
            (q for q in graph.functions if q.endswith(".handle")), None
        )
        assert service_handle is not None

        analyzer = BlastAnalyzer(graph=graph, index=index)
        report = analyzer.analyze_functions([service_handle])

        upstream_qnames = [
            f.qualified_name
            for f in report.affected_functions
            if f.severity == ImpactSeverity.UPSTREAM
        ]
        # entry.main calls service.handle → upstream
        assert any("main" in q for q in upstream_qnames), (
            f"Expected entry.main in upstream, got: {upstream_qnames}"
        )

    def test_upstream_depth_is_one(self, sample_project_index_and_graph):
        # Spec: Section 7, Criterion #3 — "a.foo has depth=1 (direct caller of b.bar)"
        index, graph = sample_project_index_and_graph

        service_handle = next(
            (q for q in graph.functions if q.endswith(".handle")), None
        )
        assert service_handle is not None

        analyzer = BlastAnalyzer(graph=graph, index=index)
        report = analyzer.analyze_functions([service_handle])

        upstream_main = next(
            (
                f
                for f in report.affected_functions
                if f.severity == ImpactSeverity.UPSTREAM and "main" in f.qualified_name
            ),
            None,
        )
        assert upstream_main is not None
        assert upstream_main.depth == 1

    def test_downstream_depth_is_one(self, sample_project_index_and_graph):
        # Spec: Section 7, Criterion #3 — "c.baz has depth=1 (direct callee of b.bar)"
        index, graph = sample_project_index_and_graph

        service_handle = next(
            (q for q in graph.functions if q.endswith(".handle")), None
        )
        assert service_handle is not None

        analyzer = BlastAnalyzer(graph=graph, index=index)
        report = analyzer.analyze_functions([service_handle])

        downstream_work = next(
            (
                f
                for f in report.affected_functions
                if f.severity == ImpactSeverity.DOWNSTREAM
                and "work" in f.qualified_name
            ),
            None,
        )
        assert downstream_work is not None
        assert downstream_work.depth == 1

    def test_upstream_path_from_change(self, sample_project_index_and_graph):
        # Spec: Section 7, Criterion #3 — "path_from_change for a.foo is [b.bar, a.foo]"
        index, graph = sample_project_index_and_graph

        service_handle = next(
            (q for q in graph.functions if q.endswith(".handle")), None
        )
        assert service_handle is not None

        analyzer = BlastAnalyzer(graph=graph, index=index)
        report = analyzer.analyze_functions([service_handle])

        upstream_main = next(
            (
                f
                for f in report.affected_functions
                if f.severity == ImpactSeverity.UPSTREAM and "main" in f.qualified_name
            ),
            None,
        )
        assert upstream_main is not None
        # path_from_change should start with the changed function
        assert upstream_main.path_from_change[0] == service_handle
        # path_from_change should end with the affected function
        assert upstream_main.path_from_change[-1] == upstream_main.qualified_name

    def test_changed_function_in_affected_as_direct(
        self, sample_project_index_and_graph
    ):
        # Changed functions are now included in affected_functions with
        # severity=DIRECT, depth=0 — one uniform list for consumers.
        index, graph = sample_project_index_and_graph

        service_handle = next(
            (q for q in graph.functions if q.endswith(".handle")), None
        )
        assert service_handle is not None

        analyzer = BlastAnalyzer(graph=graph, index=index)
        report = analyzer.analyze_functions([service_handle])

        by_qname = {f.qualified_name: f for f in report.affected_functions}
        assert service_handle in by_qname
        direct = by_qname[service_handle]
        assert direct.severity == ImpactSeverity.DIRECT
        assert direct.depth == 0
        assert direct.path_from_change == [service_handle]

    def test_changed_function_in_changed_functions_list(
        self, sample_project_index_and_graph
    ):
        # Spec: Section 7, Criterion #3 — "report.changed_functions contains the input qname"
        index, graph = sample_project_index_and_graph

        service_handle = next(
            (q for q in graph.functions if q.endswith(".handle")), None
        )
        assert service_handle is not None

        analyzer = BlastAnalyzer(graph=graph, index=index)
        report = analyzer.analyze_functions([service_handle])

        assert service_handle in report.changed_functions

    def test_no_function_appears_twice(self, sample_project_index_and_graph):
        # Spec: Section 11 — "cycles: each function appears at most once"
        index, graph = sample_project_index_and_graph

        service_handle = next(
            (q for q in graph.functions if q.endswith(".handle")), None
        )
        assert service_handle is not None

        analyzer = BlastAnalyzer(graph=graph, index=index)
        report = analyzer.analyze_functions([service_handle])

        qnames = [f.qualified_name for f in report.affected_functions]
        assert len(qnames) == len(set(qnames)), "Duplicate qnames in affected_functions"


class TestBlastAnalyzerEntryPoints:
    # Spec: Section 7, Criterion #4 — "entry points hit when utility function changed"

    def test_entry_point_detected_for_changed_utility(self):
        # Spec: Section 7, Criterion #4 — "route endpoint in affected_entry_points"
        index, graph = _build_fastapi_index()

        # get_all_users is called by list_users which is an @app.get route
        get_all_users = next(
            (q for q in graph.functions if q.endswith(".get_all_users")), None
        )
        if get_all_users is None:
            pytest.skip("get_all_users not resolved in graph — cannot test AC-4")

        analyzer = BlastAnalyzer(graph=graph, index=index)
        report = analyzer.analyze_functions([get_all_users])

        entry_qnames = [ep.qualified_name for ep in report.affected_entry_points]
        assert any("list_users" in q for q in entry_qnames), (
            f"Expected list_users in affected_entry_points, got: {entry_qnames}"
        )

    def test_entry_point_has_trigger(self):
        # Spec: Section 7, Criterion #4 — "AffectedEntryPoint.trigger is non-empty"
        index, graph = _build_fastapi_index()

        get_all_users = next(
            (q for q in graph.functions if q.endswith(".get_all_users")), None
        )
        if get_all_users is None:
            pytest.skip("get_all_users not resolved in graph — cannot test AC-4")

        analyzer = BlastAnalyzer(graph=graph, index=index)
        report = analyzer.analyze_functions([get_all_users])

        for ep in report.affected_entry_points:
            assert ep.trigger, f"Entry point {ep.qualified_name} has empty trigger"

    def test_entry_point_reached_via_not_empty(self):
        # Spec: Section 7, Criterion #4 — "AffectedEntryPoint.reached_via is non-empty"
        index, graph = _build_fastapi_index()

        get_all_users = next(
            (q for q in graph.functions if q.endswith(".get_all_users")), None
        )
        if get_all_users is None:
            pytest.skip("get_all_users not resolved in graph — cannot test AC-4")

        analyzer = BlastAnalyzer(graph=graph, index=index)
        report = analyzer.analyze_functions([get_all_users])

        for ep in report.affected_entry_points:
            assert ep.reached_via, (
                f"Entry point {ep.qualified_name} has empty reached_via"
            )


class TestBlastAnalyzerDepthLimit:
    # Spec: Section 7, Criterion #10 — "depth limit respected"

    def test_no_affected_function_exceeds_depth(self, sample_project_index_and_graph):
        # Spec: Section 7, Criterion #10 — "no AffectedFunction has depth > max_depth"
        index, graph = sample_project_index_and_graph

        util_calc = next((q for q in graph.functions if q.endswith(".calc")), None)
        assert util_calc is not None, "util.calc not found"

        analyzer = BlastAnalyzer(graph=graph, index=index)
        report = analyzer.analyze_functions([util_calc], max_depth=2)

        for f in report.affected_functions:
            assert f.depth <= 2, f"{f.qualified_name} has depth {f.depth} > max_depth 2"

    def test_stats_max_depth_respects_limit(self, sample_project_index_and_graph):
        # Spec: Section 7, Criterion #10 — "stats.max_depth <= depth param"
        index, graph = sample_project_index_and_graph

        util_calc = next((q for q in graph.functions if q.endswith(".calc")), None)
        assert util_calc is not None

        analyzer = BlastAnalyzer(graph=graph, index=index)
        report = analyzer.analyze_functions([util_calc], max_depth=2)

        assert report.stats.max_depth <= 2

    def test_depth_one_only_direct_neighbors(self, sample_project_index_and_graph):
        # Spec: Section 7, Criterion #10 — "depth=1 yields only direct neighbors"
        index, graph = sample_project_index_and_graph

        service_handle = next(
            (q for q in graph.functions if q.endswith(".handle")), None
        )
        assert service_handle is not None

        analyzer = BlastAnalyzer(graph=graph, index=index)
        report = analyzer.analyze_functions([service_handle], max_depth=1)

        # DIRECT entries have depth 0; DOWNSTREAM/UPSTREAM at depth=1 only.
        for f in report.affected_functions:
            if f.severity == ImpactSeverity.DIRECT:
                assert f.depth == 0
            else:
                assert f.depth == 1


class TestBlastAnalyzerNoMutation:
    # Spec: Section 7, Criterion #11 — "CallGraph not mutated by analyze_*"

    def test_edges_unchanged_after_analyze_functions(
        self, sample_project_index_and_graph
    ):
        # Spec: Section 7, Criterion #11 — "graph.edges is byte-equal before and after"
        index, graph = sample_project_index_and_graph

        edges_before = copy.deepcopy(graph.edges)
        unresolved_before = copy.deepcopy(graph.unresolved)
        functions_before = copy.deepcopy(graph.functions)

        service_handle = next(
            (q for q in graph.functions if q.endswith(".handle")), None
        )
        assert service_handle is not None

        analyzer = BlastAnalyzer(graph=graph, index=index)
        analyzer.analyze_functions([service_handle])

        assert graph.edges == edges_before
        assert graph.unresolved == unresolved_before
        assert graph.functions == functions_before

    def test_edges_unchanged_after_analyze_files(self, sample_project_index_and_graph):
        # Spec: Section 7, Criterion #11 — "graph.edges unchanged after analyze_files"
        index, graph = sample_project_index_and_graph

        edges_before = copy.deepcopy(graph.edges)
        unresolved_before = copy.deepcopy(graph.unresolved)

        blast_dir = Path(__file__).parent.parent / "fixtures" / "blast"
        helper_path = blast_dir / "sample_project" / "helper.py"

        analyzer = BlastAnalyzer(graph=graph, index=index)
        analyzer.analyze_files([helper_path])

        assert graph.edges == edges_before
        assert graph.unresolved == unresolved_before


class TestBlastAnalyzerAnalyzeFiles:
    def test_analyze_files_returns_report(self, sample_project_index_and_graph):
        # Spec: Section 5 — "analyze_files returns BlastRadiusReport"
        from cartograph.blast.models import BlastRadiusReport

        index, graph = sample_project_index_and_graph
        blast_dir = Path(__file__).parent.parent / "fixtures" / "blast"
        helper_path = blast_dir / "sample_project" / "helper.py"

        analyzer = BlastAnalyzer(graph=graph, index=index)
        report = analyzer.analyze_files([helper_path])

        assert isinstance(report, BlastRadiusReport)

    def test_analyze_files_sets_input_kind_files(self, sample_project_index_and_graph):
        # Spec: Section 4 — "BlastInputKind.FILES when analyze_files is called"
        from cartograph.blast.models import BlastInputKind

        index, graph = sample_project_index_and_graph
        blast_dir = Path(__file__).parent.parent / "fixtures" / "blast"
        helper_path = blast_dir / "sample_project" / "helper.py"

        analyzer = BlastAnalyzer(graph=graph, index=index)
        report = analyzer.analyze_files([helper_path])

        assert report.input_kind == BlastInputKind.FILES

    def test_analyze_files_populates_changed_files(
        self, sample_project_index_and_graph
    ):
        # Spec: Section 4 — "changed_files contains the input file paths"
        index, graph = sample_project_index_and_graph
        blast_dir = Path(__file__).parent.parent / "fixtures" / "blast"
        helper_path = blast_dir / "sample_project" / "helper.py"

        analyzer = BlastAnalyzer(graph=graph, index=index)
        report = analyzer.analyze_files([helper_path])

        assert len(report.changed_files) > 0

    def test_unknown_file_does_not_crash(self, sample_project_index_and_graph):
        # Spec: Section 11 — "unknown file: warn, continue, do not fail"
        index, graph = sample_project_index_and_graph
        analyzer = BlastAnalyzer(graph=graph, index=index)
        # Should not raise — just silently skip or warn
        report = analyzer.analyze_files([Path("nonexistent_totally_made_up.py")])
        assert report is not None
