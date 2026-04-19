"""CliPresenter."""

from __future__ import annotations

from pathlib import Path

from cartograph.v2.ir.analyzed import (
    AnalyzedGraph,
    ApiRouteEntry,
    CeleryTaskEntry,
    DiscoveredEntry,
    SignalHandlerEntry,
)
from cartograph.v2.ir.annotated import AnnotatedGraph
from cartograph.v2.ir.resolved import Edge, FunctionRef, ResolvedGraph
from cartograph.v2.stages.present.cli import CliPresenter


def _fn(qname: str) -> FunctionRef:
    return FunctionRef(
        qname=qname,
        name=qname.rsplit(".", 1)[-1],
        module=qname.rsplit(".", 1)[0],
        line_start=1,
        line_end=5,
        source_path=Path("/tmp/x.py"),
    )


def _analyzed(entries: tuple, resolved: ResolvedGraph | None = None) -> AnalyzedGraph:
    if resolved is None:
        resolved = ResolvedGraph(functions={}, edges=())
    return AnalyzedGraph(
        annotated=AnnotatedGraph(resolved=resolved),
        entry_points=entries,
    )


class TestRendering:
    def test_header_includes_counts(self):
        resolved = ResolvedGraph(
            functions={"a.f": _fn("a.f"), "a.g": _fn("a.g")},
            edges=(Edge(caller_qname="a.f", callee_qname="a.g", line=1),),
        )
        g = _analyzed(entries=(), resolved=resolved)
        out = CliPresenter().render(g, {}).decode()
        assert "functions      2" in out
        assert "edges          1" in out
        assert "entry points   0" in out

    def test_empty_graph_renders_cleanly(self):
        g = _analyzed(entries=())
        out = CliPresenter().render(g, {}).decode()
        assert "CARTOGRAPH v2" in out
        assert "entry points   0" in out

    def test_api_route_formatted(self):
        g = _analyzed(
            entries=(ApiRouteEntry(qname="app.home", method="GET", path="/users/{id}"),)
        )
        out = CliPresenter().render(g, {}).decode()
        assert "GET" in out
        assert "/users/{id}" in out
        assert "app.home" in out

    def test_celery_task_formatted(self):
        g = _analyzed(entries=(CeleryTaskEntry(qname="tasks.send", queue="priority"),))
        out = CliPresenter().render(g, {}).decode()
        assert "tasks.send" in out
        assert "[priority]" in out

    def test_discovered_entry_shows_trigger_decorator(self):
        g = _analyzed(
            entries=(
                DiscoveredEntry(qname="cli.scan", trigger_decorator="main.command"),
            )
        )
        out = CliPresenter().render(g, {}).decode()
        assert "cli.scan" in out
        assert "@main.command" in out

    def test_signal_handler_formatted(self):
        g = _analyzed(
            entries=(
                SignalHandlerEntry(
                    qname="app.on_save",
                    signal_name="post_save",
                    sender="User",
                ),
            )
        )
        out = CliPresenter().render(g, {}).decode()
        assert "app.on_save" in out
        assert "post_save" in out
        assert "User" in out

    def test_entries_grouped_by_kind(self):
        g = _analyzed(
            entries=(
                DiscoveredEntry(qname="a.first", trigger_decorator="x"),
                ApiRouteEntry(qname="b.route", method="GET", path="/"),
                DiscoveredEntry(qname="a.second", trigger_decorator="x"),
            )
        )
        out = CliPresenter().render(g, {}).decode()
        # Group headers with counts are present.
        assert "api_route (1)" in out
        assert "discovered (2)" in out

    def test_output_is_deterministic(self):
        """Sort order within kinds is stable → byte-equal outputs across runs."""
        g = _analyzed(
            entries=(
                DiscoveredEntry(qname="z.second", trigger_decorator="x"),
                DiscoveredEntry(qname="a.first", trigger_decorator="x"),
            )
        )
        a = CliPresenter().render(g, {})
        b = CliPresenter().render(g, {})
        assert a == b
        # And alphabetical within kind
        text = a.decode()
        assert text.index("a.first") < text.index("z.second")
