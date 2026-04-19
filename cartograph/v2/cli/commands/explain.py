"""carto2 explain — LLM-narrate a flow via pydantic-ai."""

from __future__ import annotations

from pathlib import Path

import click

from cartograph.v2.cli._group import main
from cartograph.v2.cli._shared import build_graph, require_qname, resolve_path


@main.command()
@click.argument("qname")
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--depth", default=4, type=int, show_default=True)
@click.option("--model", default=None, help="pydantic-ai model string")
def explain(qname: str, path: Path | None, depth: int, model: str | None) -> None:
    """LLM-narrate the flow rooted at QNAME (pydantic-ai → Claude direct)."""
    from cartograph.v2.stages.present.llm import LlmPresenter

    resolved_path = resolve_path(path)
    graph = build_graph(resolved_path, include_tests=False)
    qname = require_qname(graph.annotated.resolved.functions, qname)
    options: dict = {"entry_qname": qname, "depth": depth}
    if model:
        options["model"] = model
    click.echo(LlmPresenter().render(graph, options).decode())
