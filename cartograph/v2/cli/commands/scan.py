"""carto2 scan — re-run the pipeline and print a summary."""

from __future__ import annotations

from pathlib import Path

import click

from cartograph.v2.cli._group import main
from cartograph.v2.cli._render import pretty_scan
from cartograph.v2.cli._shared import build_graph, parse_exclude_dirs, resolve_path


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--include-tests/--no-tests", default=False, show_default=True)
@click.option(
    "--exclude-dirs",
    default=None,
    help="Comma-separated directory names to exclude beyond defaults.",
)
def scan(path: Path | None, include_tests: bool, exclude_dirs: str | None) -> None:
    """Scan a project and print a summary."""
    extra = parse_exclude_dirs(exclude_dirs)
    resolved_path = resolve_path(path)
    graph = build_graph(resolved_path, include_tests, extra_exclude=extra)
    pretty_scan(graph, resolved_path)
