"""Content-addressed caches for extract (per file) and resolve (per project).

Keys are blake2b-256 hex; serialization goes through pydantic. A malformed
entry is a miss, not an error.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from pathlib import Path

from pydantic import ValidationError

from cartograph.v2.ir.resolved import ResolvedGraph
from cartograph.v2.ir.syntactic import SyntacticModule


def content_hash(path: Path) -> str:
    return hashlib.blake2b(path.read_bytes(), digest_size=32).hexdigest()


def project_fingerprint(
    modules: Iterable[SyntacticModule], *, resolver_version: str
) -> str:
    """Compute a cache key over the set of Stage 1 outputs + resolver version.

    Any change to a file's content, a module being added/removed, or switching
    resolvers produces a different fingerprint. Path itself is not hashed —
    module_name is the stable cross-run identifier.
    """
    parts = [f"resolver:{resolver_version}"]
    for m in sorted(modules, key=lambda m: m.module_name):
        parts.append(f"{m.module_name}:{m.content_hash}")
    joined = "\n".join(parts).encode()
    return hashlib.blake2b(joined, digest_size=32).hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    """Write-then-rename. os.replace is atomic on POSIX + Windows; a crash
    mid-write leaves the previous file intact instead of a half-written
    one that would fail to parse and be treated as a permanent miss."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


class ExtractCache:
    """On-disk cache of SyntacticModules keyed by content hash."""

    def __init__(self, project_root: Path) -> None:
        self.root = (project_root / ".cartograph" / "v2" / "extract").resolve()

    def get(self, key: str) -> SyntacticModule | None:
        path = self.root / f"{key}.json"
        if not path.exists():
            return None
        try:
            return SyntacticModule.model_validate_json(path.read_bytes())
        except (ValidationError, OSError, ValueError):
            return None

    def put(self, key: str, module: SyntacticModule) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.root / f"{key}.json", module.model_dump_json())

    def clear(self) -> None:
        if not self.root.exists():
            return
        for entry in self.root.iterdir():
            if entry.suffix == ".json":
                entry.unlink()


class ResolveCache:
    """On-disk cache of ResolvedGraphs keyed by project fingerprint."""

    def __init__(self, project_root: Path) -> None:
        self.root = (project_root / ".cartograph" / "v2" / "resolve").resolve()

    def get(self, key: str) -> ResolvedGraph | None:
        path = self.root / f"{key}.json"
        if not path.exists():
            return None
        try:
            return ResolvedGraph.model_validate_json(path.read_bytes())
        except (ValidationError, OSError, ValueError):
            return None

    def put(self, key: str, graph: ResolvedGraph) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.root / f"{key}.json", graph.model_dump_json())

    def clear(self) -> None:
        if not self.root.exists():
            return
        for entry in self.root.iterdir():
            if entry.suffix == ".json":
                entry.unlink()
