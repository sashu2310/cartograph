"""RunConfig — the immutable, user-facing configuration for a v2 pipeline run.

All user-tunable inputs (project root, test inclusion, exclude list) live here.
Stage implementations (extractor, resolver, …) are NOT config — they're
composed into a `Pipeline` directly.
"""

from __future__ import annotations

from pathlib import Path

from cartograph.v2.ir.base import IR

DEFAULT_EXCLUDE_DIRS = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        ".eggs",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
        "migrations",
        ".claude",
        ".cartograph",
    }
)


class RunConfig(IR):
    """Inputs for one pipeline invocation."""

    project_root: Path
    include_tests: bool = False
    exclude_dirs: frozenset[str] = DEFAULT_EXCLUDE_DIRS
    use_cache: bool = True
