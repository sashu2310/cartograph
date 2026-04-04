"""Project configuration for CARTOGRAPH."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


DEFAULT_EXCLUDE_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    ".eggs", "dist", "build", ".tox", ".mypy_cache",
    "migrations", ".claude", ".cartograph",
}


@dataclass
class CartographConfig:
    """Configuration for a CARTOGRAPH analysis run."""

    root_path: str
    exclude_dirs: set[str] = field(default_factory=lambda: DEFAULT_EXCLUDE_DIRS.copy())
    include_tests: bool = False
    framework_hints: list[str] = field(default_factory=lambda: ["django_ninja", "celery"])
    cache_dir: Optional[str] = None

    def __post_init__(self):
        if not self.include_tests:
            self.exclude_dirs.add("tests")
            self.exclude_dirs.add("test")

        if self.cache_dir is None:
            self.cache_dir = str(Path(self.root_path) / ".cartograph")

    @property
    def root(self) -> Path:
        return Path(self.root_path)
