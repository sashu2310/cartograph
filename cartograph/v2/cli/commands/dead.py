"""carto2 dead — report functions/classes with zero incoming edges."""

from __future__ import annotations

from pathlib import Path

import click

from cartograph.v2.cli._group import main
from cartograph.v2.cli._shared import build_graph, resolve_path


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option(
    "--kind",
    type=click.Choice(["function", "method", "class"]),
    default=None,
    help="Restrict to one kind of dead symbol.",
)
@click.option(
    "--limit",
    default=50,
    type=int,
    show_default=True,
    help="Max rows per kind-table before truncation.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write findings as JSON to this file instead of printing a table.",
)
def dead(path: Path | None, kind: str | None, limit: int, output: Path | None) -> None:
    """Report functions and classes with zero incoming edges and no entry-point
    status — candidates for deletion, pending review for dynamic dispatch.

    Heuristic. May flag library-intended exports or code reached via getattr /
    __getattr__ / string-indexed callable maps. Treat as a starting list."""
    import json as _json

    from rich.console import Console
    from rich.table import Table

    from cartograph.v2.analyses import find_dead

    resolved_path = resolve_path(path)
    graph = build_graph(resolved_path, include_tests=False)
    findings = list(find_dead(graph))
    if kind is not None:
        findings = [f for f in findings if f.kind == kind]

    if output is not None:
        payload = [f.model_dump() for f in findings]
        output.write_text(_json.dumps(payload, indent=2))
        click.echo(f"wrote {output} ({len(findings)} dead)", err=True)
        return

    if not findings:
        click.echo("[no dead code found]")
        return

    console = Console()
    # Group by kind for readability — classes and methods cluster separately
    # from top-level functions.
    by_kind: dict[str, list] = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)

    for kind in ("function", "method", "class"):
        rows = sorted(by_kind.get(kind, []), key=lambda f: f.qname)
        if not rows:
            continue
        t = Table(
            title=f"dead {kind}s ({len(rows)})",
            title_style="bold red",
            header_style="bold",
        )
        t.add_column("qname", style="dim")
        t.add_column("location", style="dim cyan")
        for f in rows[:limit]:
            fname = Path(f.source_path).name
            t.add_row(f.qname, f"{fname}:{f.line_start}")
        console.print(t)
        if len(rows) > limit:
            plural_kind = kind if kind != "class" else "classe"
            console.print(
                f"[dim]… +{len(rows) - limit} more {plural_kind}s"
                f" (raise --limit to see more)[/]"
            )
        console.print()

    console.print(
        "[dim]Heuristic: dynamic dispatch (getattr, __getattr__, "
        "string-indexed callables) can bypass the static graph. "
        "Review before deleting.[/]"
    )
