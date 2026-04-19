"""Cartograph v2 — harnessing deterministic context for LLMs.

Turns any Python codebase into a deterministic call graph (entry points,
edges, async kinds, ORM sites) for LLMs and humans to consume with
ground-truth confidence instead of guessing from raw source.

See docs/v2/architecture.md.
"""

from __future__ import annotations

import os

import logfire

# Default: only warn+ reaches the console so stage-timing spans don't mingle
# with CLI output. Set CARTOGRAPH_LOG=info (or =debug) when debugging.
_LOG_LEVEL = os.getenv("CARTOGRAPH_LOG", "warn")

logfire.configure(
    send_to_logfire=False,
    service_name="cartograph-v2",
    console=logfire.ConsoleOptions(min_log_level=_LOG_LEVEL),
)
