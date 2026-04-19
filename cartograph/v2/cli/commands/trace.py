"""carto2 trace — walk the call tree rooted at QNAME."""

from __future__ import annotations

from pathlib import Path

import click

from cartograph.v2.cli._group import main
from cartograph.v2.cli._render import print_rich_tree
from cartograph.v2.cli._shared import build_graph, require_qname, resolve_path


@main.command()
@click.argument("qname")
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--depth", default=5, type=int, show_default=True)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the trace as JSON to this file instead of printing a tree.",
)
def trace(qname: str, path: Path | None, depth: int, output: Path | None) -> None:
    """Walk the call tree rooted at QNAME.

    Prints an indented tree to stdout by default. With `-o PATH`, writes a
    JSON document (nodes + edges + metadata — same shape the web viewer
    consumes) suitable for piping into other tools.
    """
    import json as _json

    from cartograph.v2.stages.present.web_serializers import serialize_graph_trace

    resolved_path = resolve_path(path)
    graph = build_graph(resolved_path, include_tests=False)
    resolved = graph.annotated.resolved
    qname = require_qname(resolved.functions, qname)
    if output is not None:
        payload = serialize_graph_trace(graph, qname, depth)
        output.write_text(_json.dumps(payload, indent=2))
        click.echo(f"wrote {output} ({len(payload['edges'])} edges)", err=True)
        return
    print_rich_tree(resolved, qname, depth=depth)
