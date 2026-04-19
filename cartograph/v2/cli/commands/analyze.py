"""carto2 analyze — engineering-insight analyses over the graph."""

from __future__ import annotations

from pathlib import Path

import click

from cartograph.v2.cli._group import main
from cartograph.v2.cli._render import pretty_analysis
from cartograph.v2.cli._shared import build_graph, resolve_path


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option(
    "--limit",
    default=20,
    type=int,
    show_default=True,
    help="Max rows per analysis table before truncation.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the full report as JSON to this file instead of printing tables.",
)
def analyze(path: Path | None, limit: int, output: Path | None) -> None:
    """Engineering-insight analyses over the graph.

    Reports N+1 ORM candidates, model hotspots, mixed-operation functions,
    and async-boundary crossings (functions touching DB + async dispatch).
    """
    from cartograph.v2.analyses import analyze as run_analyses

    resolved_path = resolve_path(path)
    graph = build_graph(resolved_path, include_tests=False)
    report = run_analyses(graph)

    if output is not None:
        output.write_text(report.model_dump_json(indent=2))
        click.echo(f"wrote {output}", err=True)
        return

    pretty_analysis(report, limit=limit)
