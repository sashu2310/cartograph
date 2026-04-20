"""carto2 coverage — static test-reachability per project function."""

from __future__ import annotations

from pathlib import Path

import click

from cartograph.v2.cli._group import main
from cartograph.v2.cli._shared import build_graph, parse_exclude_dirs, resolve_path


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option(
    "--show",
    type=click.Choice(["uncovered", "covered", "all"]),
    default="uncovered",
    show_default=True,
    help="Which coverage rows to display.",
)
@click.option(
    "--limit",
    default=50,
    type=int,
    show_default=True,
    help="Max rows in the coverage table before truncation.",
)
@click.option(
    "--exclude-dirs",
    default=None,
    help="Comma-separated directory names to exclude beyond defaults.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write coverage rows as JSON to this file instead of printing a table.",
)
def coverage(
    path: Path | None,
    show: str,
    limit: int,
    exclude_dirs: str | None,
    output: Path | None,
) -> None:
    """Which project functions are reachable from the test tree."""
    import json as _json

    from rich.console import Console
    from rich.table import Table

    from cartograph.v2.analyses import find_coverage

    extra = parse_exclude_dirs(exclude_dirs)
    resolved_path = resolve_path(path)
    graph = build_graph(resolved_path, include_tests=True, extra_exclude=extra)
    rows = list(find_coverage(graph))

    covered = sum(1 for r in rows if r.has_test_coverage)
    uncovered = len(rows) - covered

    if output is not None:
        payload = [r.model_dump() for r in rows]
        output.write_text(_json.dumps(payload, indent=2))
        click.echo(
            f"wrote {output} ({covered} covered / {uncovered} uncovered)",
            err=True,
        )
        return

    if not rows:
        click.echo("[no project functions to report on]")
        return

    if show == "uncovered":
        display = [r for r in rows if not r.has_test_coverage]
        title = f"uncovered functions ({len(display)}/{len(rows)})"
        title_style = "bold yellow"
    elif show == "covered":
        display = [r for r in rows if r.has_test_coverage]
        title = f"covered functions ({len(display)}/{len(rows)})"
        title_style = "bold green"
    else:
        display = rows
        title = f"coverage ({covered} covered / {uncovered} uncovered)"
        title_style = "bold"

    console = Console()
    if not display:
        console.print(f"[dim]no rows to show for --show {show}[/]")
        _print_footer(console, covered, uncovered)
        return

    t = Table(title=title, title_style=title_style, header_style="bold")
    t.add_column("qname", style="dim")
    t.add_column("covered", style="dim cyan")
    for row in display[:limit]:
        marker = "[green]yes[/]" if row.has_test_coverage else "[yellow]no[/]"
        t.add_row(row.qname, marker)
    console.print(t)
    if len(display) > limit:
        console.print(
            f"[dim]… +{len(display) - limit} more rows (raise --limit to see more)[/]"
        )
    _print_footer(console, covered, uncovered)


def _print_footer(console, covered: int, uncovered: int) -> None:
    total = covered + uncovered
    pct = (covered / total * 100.0) if total else 0.0
    console.print(
        f"[dim]static coverage: {covered}/{total} ({pct:.1f}%). "
        "Heuristic — dynamic dispatch can reach code this view misses.[/]"
    )
