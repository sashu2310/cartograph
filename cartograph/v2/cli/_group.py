"""Click group + -v/--verbose wiring shared by every command module."""

from __future__ import annotations

import click


def _verbose_callback(_ctx, _param, value):
    """Reconfigure logfire to emit INFO spans when `-v/--verbose` is set.

    logfire is configured at import time (see cartograph/v2/__init__.py) —
    running it again here with a lower min-log-level replaces the sink
    before any command starts, so stage-timing spans print inline.
    """
    if value:
        import logfire

        logfire.configure(
            send_to_logfire=False,
            service_name="cartograph-v2",
            console=logfire.ConsoleOptions(min_log_level="info"),
        )
    return value


@click.group()
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    expose_value=False,
    is_eager=True,
    callback=_verbose_callback,
    help="Stream stage-timing spans (extract, resolve, annotate, discover) to stderr.",
)
def main() -> None:
    """Cartograph v2 — harnessing deterministic context for LLMs."""
