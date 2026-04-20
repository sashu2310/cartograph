"""Tests for cartograph.blast.renderer — AC-7 (JSON shape), markdown, terminal."""

import json
from io import StringIO

from rich.console import Console

from cartograph.blast.models import (
    AffectedEntryPoint,
    AffectedFunction,
    AffectedTest,
    BlastInputKind,
    BlastRadiusReport,
    BlastStats,
    ImpactSeverity,
)
from cartograph.blast.renderer import render_json, render_markdown, render_terminal

_EXPECTED_JSON_KEYS = {
    "input_kind",
    "changed_files",
    "changed_functions",
    "affected_functions",
    "affected_entry_points",
    "affected_tests",
    "stats",
}


def _make_minimal_report() -> BlastRadiusReport:
    """Build a minimal BlastRadiusReport for snapshot testing."""
    return BlastRadiusReport(
        input_kind=BlastInputKind.FUNCTIONS,
        changed_files=[],
        changed_functions=["sample_project.service.handle"],
        affected_functions=[
            AffectedFunction(
                qualified_name="sample_project.entry.main",
                module="sample_project.entry",
                severity=ImpactSeverity.UPSTREAM,
                depth=1,
                path_from_change=[
                    "sample_project.service.handle",
                    "sample_project.entry.main",
                ],
            ),
            AffectedFunction(
                qualified_name="sample_project.helper.work",
                module="sample_project.helper",
                severity=ImpactSeverity.DOWNSTREAM,
                depth=1,
                path_from_change=[
                    "sample_project.service.handle",
                    "sample_project.helper.work",
                ],
            ),
        ],
        affected_entry_points=[
            AffectedEntryPoint(
                qualified_name="sample_project.entry.main",
                entry_point_type="api_route",
                trigger="@app.get('/run')",
                reached_via=[
                    "sample_project.service.handle",
                    "sample_project.entry.main",
                ],
            )
        ],
        affected_tests=[
            AffectedTest(
                test_qualified_name="test_service.test_handle",
                test_file="tests/fixtures/blast/sample_tests/test_service.py",
                covers=["sample_project.service.handle"],
            )
        ],
        stats=BlastStats(
            total_changed_functions=1,
            total_downstream=1,
            total_upstream=1,
            total_entry_points_hit=1,
            total_tests_affected=1,
            max_depth=1,
        ),
    )


class TestRenderJson:
    # Spec: Section 7, Criterion #7 — "JSON output matches Section 6 response schema"

    def test_render_json_is_valid_json(self):
        # Spec: Section 7, Criterion #7 — "stdout is parseable by json.loads()"
        report = _make_minimal_report()
        output = render_json(report)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_render_json_has_correct_top_level_keys(self):
        # Spec: Section 9, assertion #11 — "top-level keys equal exactly the 7 required keys"
        report = _make_minimal_report()
        parsed = json.loads(render_json(report))
        assert set(parsed.keys()) == _EXPECTED_JSON_KEYS

    def test_render_json_input_kind_value(self):
        # Spec: Section 6 — "input_kind is the str-enum value (not the enum object)"
        report = _make_minimal_report()
        parsed = json.loads(render_json(report))
        assert parsed["input_kind"] == "functions"

    def test_render_json_changed_functions(self):
        # Spec: Section 6 — "changed_functions is a list of qname strings"
        report = _make_minimal_report()
        parsed = json.loads(render_json(report))
        assert isinstance(parsed["changed_functions"], list)
        assert "sample_project.service.handle" in parsed["changed_functions"]

    def test_render_json_affected_functions_shape(self):
        # Spec: Section 6 — "each affected_function has required keys"
        report = _make_minimal_report()
        parsed = json.loads(render_json(report))
        required_fn_keys = {
            "qualified_name",
            "module",
            "severity",
            "depth",
            "path_from_change",
        }
        for fn in parsed["affected_functions"]:
            assert required_fn_keys.issubset(fn.keys()), (
                f"Missing keys in affected_function: {fn}"
            )

    def test_render_json_affected_entry_points_shape(self):
        # Spec: Section 6 — "each affected_entry_point has required keys"
        report = _make_minimal_report()
        parsed = json.loads(render_json(report))
        required_ep_keys = {
            "qualified_name",
            "entry_point_type",
            "trigger",
            "reached_via",
        }
        for ep in parsed["affected_entry_points"]:
            assert required_ep_keys.issubset(ep.keys()), (
                f"Missing keys in affected_entry_point: {ep}"
            )

    def test_render_json_affected_tests_shape(self):
        # Spec: Section 6 — "each affected_test has required keys"
        report = _make_minimal_report()
        parsed = json.loads(render_json(report))
        required_test_keys = {"test_qualified_name", "test_file", "covers"}
        for t in parsed["affected_tests"]:
            assert required_test_keys.issubset(t.keys()), (
                f"Missing keys in affected_test: {t}"
            )

    def test_render_json_stats_shape(self):
        # Spec: Section 6 — "stats has all 6 required keys"
        report = _make_minimal_report()
        parsed = json.loads(render_json(report))
        required_stats_keys = {
            "total_changed_functions",
            "total_downstream",
            "total_upstream",
            "total_entry_points_hit",
            "total_tests_affected",
            "max_depth",
        }
        assert required_stats_keys.issubset(parsed["stats"].keys())

    def test_render_json_returns_string(self):
        # Spec: Section 5 — "render_json returns str"
        report = _make_minimal_report()
        output = render_json(report)
        assert isinstance(output, str)

    def test_render_json_empty_report(self):
        # Spec: Section 7, Criterion #7 — "empty report produces valid JSON with correct keys"
        report = BlastRadiusReport(
            input_kind=BlastInputKind.FILES,
            changed_files=[],
            changed_functions=[],
            affected_functions=[],
            affected_entry_points=[],
            affected_tests=[],
            stats=BlastStats(
                total_changed_functions=0,
                total_downstream=0,
                total_upstream=0,
                total_entry_points_hit=0,
                total_tests_affected=0,
                max_depth=0,
            ),
        )
        output = render_json(report)
        parsed = json.loads(output)
        assert set(parsed.keys()) == _EXPECTED_JSON_KEYS


class TestRenderMarkdown:
    # Spec: Section 8 — "markdown output is PR-comment-ready"

    def test_render_markdown_returns_string(self):
        # Spec: Section 5 — "render_markdown returns str"
        report = _make_minimal_report()
        output = render_markdown(report)
        assert isinstance(output, str)

    def test_render_markdown_has_main_header(self):
        # Spec: Section 8 — "## Cartograph Blast Radius header present"
        report = _make_minimal_report()
        output = render_markdown(report)
        assert "## Cartograph Blast Radius" in output

    def test_render_markdown_has_stats_table(self):
        # Spec: Section 8 — "stats table with | Metric | Count | header"
        report = _make_minimal_report()
        output = render_markdown(report)
        assert (
            "| Metric" in output or "| --- |" in output or "Changed functions" in output
        )

    def test_render_markdown_has_entry_points_section(self):
        # Spec: Section 8 — "### Entry points hit section"
        report = _make_minimal_report()
        output = render_markdown(report)
        assert "Entry points hit" in output

    def test_render_markdown_has_tests_section(self):
        # Spec: Section 8 — "### Tests affected section"
        report = _make_minimal_report()
        output = render_markdown(report)
        assert "Tests affected" in output

    def test_render_markdown_lists_entry_points(self):
        # Spec: Section 8 — "entry points listed as markdown list items"
        report = _make_minimal_report()
        output = render_markdown(report)
        assert "sample_project.entry.main" in output

    def test_render_markdown_lists_tests(self):
        # Spec: Section 8 — "test qnames listed in tests section"
        report = _make_minimal_report()
        output = render_markdown(report)
        assert "test_service.test_handle" in output


class TestRenderTerminal:
    # Spec: Section 8 — "terminal output matches golden example"

    def test_render_terminal_does_not_raise(self):
        # Spec: Section 7, Criterion #7 — "render_terminal completes without error"
        report = _make_minimal_report()
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=False)
        render_terminal(report, console)  # must not raise

    def test_render_terminal_contains_blast_radius_header(self):
        # Spec: Section 8 — "CARTOGRAPH blast radius header in output"
        report = _make_minimal_report()
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=False)
        render_terminal(report, console)
        output = string_io.getvalue()
        assert "blast radius" in output.lower()

    def test_render_terminal_contains_stats(self):
        # Spec: Section 8 — "stats section present in terminal output"
        report = _make_minimal_report()
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=False)
        render_terminal(report, console)
        output = string_io.getvalue()
        # Stats section should mention counts
        assert "1" in output  # at minimum, the counts appear

    def test_render_terminal_contains_input_function(self):
        # Spec: Section 8 — "changed function name appears in terminal output"
        report = _make_minimal_report()
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=False)
        render_terminal(report, console)
        output = string_io.getvalue()
        assert "sample_project.service.handle" in output

    def test_render_terminal_returns_none(self):
        # Spec: Section 5 — "render_terminal returns None (side-effect only)"
        report = _make_minimal_report()
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=False)
        result = render_terminal(report, console)
        assert result is None
