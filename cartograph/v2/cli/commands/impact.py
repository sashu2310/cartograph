"""carto2 impact — report every call/import site affected by a rename."""

from __future__ import annotations

from pathlib import Path

import click

from cartograph.v2.cli._group import main
from cartograph.v2.cli._shared import build_graph, require_qname, resolve_path


@main.command()
@click.option(
    "--rename",
    required=True,
    help="Format: `old.qname:new_name`. Example: `pydantic_ai.Agent:Assistant`",
)
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the impact report as JSON to this file.",
)
def impact(path: Path | None, rename: str, output: Path | None) -> None:
    """Report every call site that would break under a symbol rename.

    Read-only — emits a plan, never modifies files. Imports are not yet
    enumerated (ImportStmt doesn't carry line numbers in the IR); the
    footer notes this so users can grep for lingering references.
    """
    from rich.console import Console
    from rich.table import Table

    from cartograph.v2.analyses import rename_impact

    if ":" not in rename:
        raise click.ClickException("expected --rename in the form `old.qname:new_name`")
    old_qname, new_name = rename.split(":", 1)
    if not new_name:
        raise click.ClickException("new name cannot be empty")

    resolved_path = resolve_path(path)
    graph = build_graph(resolved_path, include_tests=False)
    resolved_old = require_qname(graph.annotated.resolved.functions, old_qname)

    report = rename_impact(graph, resolved_old, new_name)

    if output is not None:
        output.write_text(report.model_dump_json(indent=2))
        click.echo(f"wrote {output} ({len(report.call_sites)} call sites)", err=True)
        return

    console = Console()
    console.print(
        f"[bold]rename[/]  [red]{report.old_qname}[/] → [green]{report.new_name}[/]\n"
    )
    console.print(
        f"[dim]definition:[/] {Path(report.definition_file).name}:{report.definition_line}"
    )
    console.print()

    if not report.call_sites:
        console.print("[dim](no call sites found — rename affects definition only)[/]")
    else:
        t = Table(
            title=f"call sites ({len(report.call_sites)})",
            title_style="bold red",
            header_style="bold",
        )
        t.add_column("file:line", style="dim cyan")
        t.add_column("caller", style="dim")
        for s in report.call_sites:
            fname = Path(s.file).name
            t.add_row(f"{fname}:{s.line}", s.caller_qname)
        console.print(t)
        console.print()

    if report.import_sites:
        t = Table(
            title=f"import sites ({len(report.import_sites)})",
            title_style="bold yellow",
            header_style="bold",
        )
        t.add_column("file:line", style="dim cyan")
        t.add_column("statement", style="dim")
        for s in report.import_sites:
            fname = Path(s.file).name
            t.add_row(f"{fname}:{s.line}", s.statement)
        console.print(t)
        console.print()
    else:
        console.print("[dim](no import statements reference this name)[/]")
