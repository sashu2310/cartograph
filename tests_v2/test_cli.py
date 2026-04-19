"""carto2 CLI surface smoke tests."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from cartograph.v2.cli import _shared as cli_module
from cartograph.v2.cli import main


class TestCliSurface:
    def test_help_lists_all_commands(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        out = result.output
        for cmd in (
            "init",
            "scan",
            "entries",
            "trace",
            "callers",
            "search",
            "serve",
            "explain",
            "context",
            "benchmark",
        ):
            assert cmd in out

    def test_scan_rejects_missing_path(self):
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "/nope/does/not/exist"])
        assert result.exit_code != 0

    def test_benchmark_help_shows_targets_option(self):
        runner = CliRunner()
        result = runner.invoke(main, ["benchmark", "--help"])
        assert result.exit_code == 0
        assert "--targets" in result.output

    def test_explain_help_shows_model_option(self):
        runner = CliRunner()
        result = runner.invoke(main, ["explain", "--help"])
        assert result.exit_code == 0
        assert "--model" in result.output

    def test_trace_help_shows_output_option(self):
        runner = CliRunner()
        result = runner.invoke(main, ["trace", "--help"])
        assert result.exit_code == 0
        assert "--output" in result.output
        assert "JSON" in result.output

    def test_context_help_shows_pipe_example(self):
        runner = CliRunner()
        result = runner.invoke(main, ["context", "--help"])
        assert result.exit_code == 0
        assert "claude" in result.output.lower()


class TestPathResolution:
    def test_scan_without_path_errors_when_no_last_project(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cli_module, "_LAST_PROJECT_FILE", tmp_path / "no-such-file")
        runner = CliRunner()
        result = runner.invoke(main, ["scan"])
        assert result.exit_code != 0
        assert "previous `init`" in result.output

    def test_init_persists_then_scan_resolves(self, monkeypatch, tmp_path):
        """init writes last-project; subsequent _resolve_path() picks it up."""
        monkeypatch.setattr(cli_module, "_LAST_PROJECT_FILE", tmp_path / "last")
        cli_module.save_last_project(tmp_path)
        assert cli_module.get_last_project() == tmp_path.resolve()
        assert cli_module.resolve_path(None) == tmp_path.resolve()


class TestQnameResolution:
    """_resolve_qname / _require_qname behaviour."""

    def test_exact_match_wins(self):
        fns = {"a.b.checkout": object(), "x.y.z": object()}
        assert cli_module.resolve_qname(fns, "a.b.checkout") == "a.b.checkout"

    def test_unique_suffix_resolves(self):
        fns = {"a.b.checkout": object(), "x.y.z": object()}
        assert cli_module.resolve_qname(fns, "checkout") == "a.b.checkout"

    def test_substring_fallback(self):
        fns = {"pkg.mod.checkout_flow": object(), "pkg.mod.unrelated": object()}
        # 'checkout' is not a suffix but is a substring
        assert cli_module.resolve_qname(fns, "checkout") == "pkg.mod.checkout_flow"

    def test_no_match_returns_none(self):
        fns = {"a.b.foo": object()}
        assert cli_module.resolve_qname(fns, "zzzz") is None

    def test_suggestions_are_substring_hits(self):
        fns = {
            "a.b.checkout": object(),
            "a.b.check": object(),
            "x.y.unrelated": object(),
        }
        hints = cli_module.qname_suggestions(fns, "check", n=3)
        assert set(hints) == {"a.b.checkout", "a.b.check"}

    def test_require_qname_raises_with_suggestions(self):
        import click

        fns = {"a.b.checkout_flow": object()}
        import pytest

        with pytest.raises(click.ClickException) as excinfo:
            cli_module.require_qname(fns, "zzz_no_match_zzz")
        assert "unknown qname" in str(excinfo.value.message)


class TestContextMarkdown:
    """Direct tests on the markdown renderers — no pipeline invocation."""

    def test_codebase_markdown_non_empty(self):
        from cartograph.v2.ir.analyzed import AnalyzedGraph
        from cartograph.v2.ir.annotated import AnnotatedGraph
        from cartograph.v2.ir.resolved import Edge, FunctionRef, ResolvedGraph

        fn = FunctionRef(
            qname="m.f",
            name="f",
            module="m",
            line_start=1,
            line_end=2,
            source_path=Path("/tmp/m.py"),
        )
        resolved = ResolvedGraph(
            functions={"m.f": fn},
            edges=(Edge(caller_qname="m.f", callee_qname="m.f", line=1),),
        )
        analyzed = AnalyzedGraph(
            annotated=AnnotatedGraph(resolved=resolved, labels={}),
            entry_points=(),
        )
        from cartograph.v2.stages.present.markdown import codebase_markdown

        md = codebase_markdown(analyzed)
        assert "# Codebase Analysis" in md
        assert "Functions: 1" in md
        assert "m.f" in md

    def test_flow_markdown_includes_root(self):
        from cartograph.v2.ir.analyzed import AnalyzedGraph
        from cartograph.v2.ir.annotated import AnnotatedGraph
        from cartograph.v2.ir.resolved import FunctionRef, ResolvedGraph

        fn = FunctionRef(
            qname="m.root",
            name="root",
            module="m",
            line_start=10,
            line_end=20,
            source_path=Path("/tmp/m.py"),
            decorators=("app.route",),
        )
        analyzed = AnalyzedGraph(
            annotated=AnnotatedGraph(
                resolved=ResolvedGraph(functions={"m.root": fn}, edges=()),
                labels={},
            ),
            entry_points=(),
        )
        from cartograph.v2.stages.present.markdown import flow_markdown

        md = flow_markdown(analyzed, "m.root", depth=3)
        assert "m.root" in md
        assert "app.route" in md
        assert "/tmp/m.py:10" in md
