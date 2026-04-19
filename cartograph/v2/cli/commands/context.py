"""carto2 context — emit graph-as-markdown for piping to external LLMs."""

from __future__ import annotations

from pathlib import Path

import click

from cartograph.v2.cli._group import main
from cartograph.v2.cli._shared import build_graph, require_qname, resolve_path


@main.command()
@click.argument("qname", required=False)
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--depth", default=5, type=int, show_default=True)
@click.option(
    "--answer",
    default=None,
    help='Question-scoped markdown. Examples: "what calls X", "callers of X", "what does X call", "flow of X".',
)
@click.option(
    "--max-tokens",
    default=None,
    type=int,
    help="Cap the flow-context output at ~N tokens (greedy BFS; chars/4 approximation).",
)
def context(
    qname: str | None,
    path: Path | None,
    depth: int,
    answer: str | None,
    max_tokens: int | None,
) -> None:
    """Emit graph-as-markdown for piping to external LLMs.

    \b
    Usage:
      carto2 context | claude "explain this codebase"
      carto2 context checkout | claude "explain this flow"
      carto2 context --answer "what calls checkout" | claude
      carto2 context checkout --max-tokens 2000 | claude
    """
    from cartograph.v2.stages.present.markdown import (
        callees_markdown,
        callers_markdown,
        codebase_markdown,
        flow_markdown,
        parse_answer_question,
    )

    # context has two optional positional args; users often pass ONLY a path
    # (e.g. `carto2 context /tmp/fastapi`). Detect that and re-bind so the
    # arg becomes `path`, not `qname`.
    if qname is not None and path is None and Path(qname).exists():
        path = Path(qname)
        qname = None

    resolved_path = resolve_path(path)
    graph = build_graph(resolved_path, include_tests=False)

    if answer is not None:
        parsed = parse_answer_question(answer)
        if parsed is None:
            raise click.ClickException(
                f"couldn't parse question: {answer!r}. Try: "
                '"what calls X", "what does X call", "flow of X".'
            )
        kind, target = parsed
        resolved_qname = require_qname(graph.annotated.resolved.functions, target)
        if kind == "callers":
            click.echo(callers_markdown(graph, resolved_qname))
        elif kind == "callees":
            click.echo(callees_markdown(graph, resolved_qname))
        else:  # flow
            click.echo(
                flow_markdown(graph, resolved_qname, depth, max_tokens=max_tokens)
            )
        return

    if qname is None:
        click.echo(codebase_markdown(graph))
    else:
        qname = require_qname(graph.annotated.resolved.functions, qname)
        click.echo(flow_markdown(graph, qname, depth, max_tokens=max_tokens))
