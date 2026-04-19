"""carto2 serve — run the interactive Cytoscape.js DAG viewer."""

from __future__ import annotations

from pathlib import Path

import click

from cartograph.v2.cli._group import main
from cartograph.v2.cli._shared import build_graph, resolve_path


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=3333, type=int, show_default=True)
def serve(path: Path | None, host: str, port: int) -> None:
    """Run the interactive web viewer."""
    from cartograph.v2.stages.present.web import serve as serve_web

    resolved_path = resolve_path(path)
    graph = build_graph(resolved_path, include_tests=False)
    serve_web(graph, host=host, port=port, project_name=resolved_path.name)
