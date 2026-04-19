"""Command modules — importing each one fires its @main.command decorator."""

from __future__ import annotations

from cartograph.v2.cli.commands import (  # noqa: F401
    analyze,
    benchmark,
    callers,
    context,
    dead,
    entries,
    explain,
    impact,
    init,
    mcp,
    scan,
    search,
    serve,
    trace,
)
