"""carto2 — harnessing deterministic context for LLMs.

`main` is the Click group; importing this package also imports every
command module in `commands/`, whose @main.command decorators register
the subcommands against the group.
"""

from __future__ import annotations

from cartograph.v2.cli._group import main
from cartograph.v2.cli import commands  # noqa: F401 — side-effect import

__all__ = ["main"]


if __name__ == "__main__":
    main()
