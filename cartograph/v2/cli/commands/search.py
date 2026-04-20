"""carto2 search — find functions by name, ranked."""

from __future__ import annotations

from pathlib import Path

import click

from cartograph.v2.cli._group import main
from cartograph.v2.cli._shared import build_graph, resolve_path


@main.command()
@click.argument("query")
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--limit", default=20, type=int, show_default=True)
def search(query: str, path: Path | None, limit: int) -> None:
    """Find functions by name, ranked by function-name match first.

    Function-name hits are scored above module-path hits, so `search Agent`
    returns `pydantic_ai.Agent` before `weather_agent_gradio.stream_from_agent`.
    """
    from rich.console import Console

    from cartograph.v2.stages.present.util import ranked_search

    resolved_path = resolve_path(path)
    graph = build_graph(resolved_path, include_tests=False)
    resolved = graph.annotated.resolved

    hits = ranked_search(resolved, query, limit)
    if not hits:
        click.echo(f"(no matches for {query!r})")
        return
    console = Console()
    for _, qname in hits:
        fn = resolved.functions[qname]
        name = qname.rsplit(".", 1)[-1]
        kind_tag = f"[dim yellow]{fn.kind}[/]" if fn.kind != "function" else ""
        console.print(
            f"[bold white]{name}[/]  [dim]{qname}[/]  {kind_tag}  "
            f"[dim cyan]{fn.source_path.name}:{fn.line_start}[/]"
        )
