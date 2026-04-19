"""carto2 init — scan a project and remember its path."""

from __future__ import annotations

from pathlib import Path

import click

from cartograph.v2.cli._group import main
from cartograph.v2.cli._render import pretty_scan
from cartograph.v2.cli._shared import (
    build_graph,
    parse_exclude_dirs,
    save_last_project,
)


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--include-tests/--no-tests", default=False, show_default=True)
@click.option(
    "--exclude-dirs",
    default=None,
    help="Comma-separated directory names to exclude beyond defaults (e.g. `docs_src,examples,bench`).",
)
def init(path: Path, include_tests: bool, exclude_dirs: str | None) -> None:
    """Scan a project and remember its path for later commands."""
    extra = parse_exclude_dirs(exclude_dirs)
    graph = build_graph(path, include_tests, extra_exclude=extra)
    save_last_project(path)
    pretty_scan(graph, path)
    click.echo(f"\n(saved as last project: {path.resolve()})", err=True)
