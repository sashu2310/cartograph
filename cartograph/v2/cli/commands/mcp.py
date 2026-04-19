"""carto2 mcp — run an MCP server over stdio."""

from __future__ import annotations

from pathlib import Path

import click

from cartograph.v2.cli._group import main
from cartograph.v2.cli._shared import resolve_path


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
def mcp(path: Path | None) -> None:
    """Run an MCP server (stdio) exposing the pipeline to agent hosts.

    Point Claude Code at this with:
      claude mcp add cartograph -- carto2 mcp /path/to/project
    """
    from cartograph.v2.mcp.server import serve as serve_mcp

    resolved = resolve_path(path)
    serve_mcp(resolved)
