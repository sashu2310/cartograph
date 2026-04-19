"""carto2 entries — list discovered entry points, one per line."""

from __future__ import annotations

from pathlib import Path

import click

from cartograph.v2.cli._group import main
from cartograph.v2.cli._render import pretty_entry_line
from cartograph.v2.cli._shared import build_graph, resolve_path


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--kind", default=None, help="filter by entry-point kind")
def entries(path: Path | None, kind: str | None) -> None:
    """List discovered entry points (rich-rendered; same shape as `carto2 scan`)."""
    from rich.console import Console

    resolved_path = resolve_path(path)
    graph = build_graph(resolved_path, include_tests=False)

    kind_styles = {
        "api_route": "bright_blue",
        "celery_task": "magenta",
        "celery_beat": "bright_magenta",
        "signal_handler": "yellow",
        "discovered": "green",
    }

    console = Console()
    hits = [ep for ep in graph.entry_points if kind is None or ep.kind == kind]
    if not hits:
        console.print("[dim](no entry points match)[/]")
        return
    for ep in sorted(hits, key=lambda e: (e.kind, e.qname)):
        accent = kind_styles.get(ep.kind, "white")
        console.print(pretty_entry_line(ep, accent))
