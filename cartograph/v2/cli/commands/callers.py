"""carto2 callers — reverse lookup for a qname."""

from __future__ import annotations

from pathlib import Path

import click

from cartograph.v2.cli._group import main
from cartograph.v2.cli._shared import build_graph, require_qname, resolve_path


@main.command()
@click.argument("qname")
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
def callers(qname: str, path: Path | None) -> None:
    """Reverse lookup: list functions that call QNAME."""
    resolved_path = resolve_path(path)
    graph = build_graph(resolved_path, include_tests=False)
    resolved = graph.annotated.resolved
    qname = require_qname(resolved.functions, qname)
    edges = resolved.get_callers(qname)
    if not edges:
        click.echo(f"(no callers found for {qname})")
        return
    for e in edges:
        click.echo(f"{e.caller_qname}  (line {e.line})")
