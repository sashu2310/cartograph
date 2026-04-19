"""Content-addressed caches for extract (per file) and resolve (per project).

Keys are blake2b-256 hex; serialization goes through pydantic. A malformed
entry is a miss, not an error.

Stage 1 mtime fast path: ExtractCache keeps a secondary `path → (mtime,
hash)` index alongside the hash-keyed primary store. On lookup, if the
file's mtime matches the recorded value, we skip re-hashing the bytes
and reuse the known hash. mtime is a lossy freshness signal, but we
only use it to skip an already-done hash computation - if mtime moved,
we re-hash and correct the index. No correctness risk, ~100-500 ms
saved on 30K-file repeat scans.
"""

from __future__ import annotations

import hashlib
import json
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
    """On-disk cache of SyntacticModules keyed by content hash.

    Also maintains a secondary `path → (mtime, hash)` index so repeat
    scans against unchanged files skip the blake2b-over-bytes step and
    reuse the known hash. Call `hash_for(path)` instead of
    `content_hash(path)` directly to benefit. Call `save_mtime_index()`
    once per pipeline run to persist the index.
    """

    _MTIME_INDEX_NAME = "mtime_index.json"

    def __init__(self, project_root: Path) -> None:
        self.root = (project_root / ".cartograph" / "v2" / "extract").resolve()
        # {path_str: [mtime, hash]} — JSON-friendly list form on disk.
        self._mtime_index: dict[str, list] = self._load_mtime_index()
        self._mtime_dirty = False

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

    def hash_for(self, path: Path) -> str:
        """Content hash for `path`, short-circuiting the file read when the
        file's mtime matches what we already hashed. Mtime mismatches fall
        through to a fresh blake2b over the bytes and update the index.
        """
        resolved_path = str(path.resolve())
        try:
            current_mtime = os.stat(path).st_mtime
        except OSError:
            # If we can't stat, fall back to hashing — content_hash will
            # raise an OSError of its own, which upstream already handles.
            return content_hash(path)

        recorded = self._mtime_index.get(resolved_path)
        if recorded is not None and recorded[0] == current_mtime:
            return recorded[1]

        digest = content_hash(path)
        self._mtime_index[resolved_path] = [current_mtime, digest]
        self._mtime_dirty = True
        return digest

    def save_mtime_index(self) -> None:
        """Persist the path→(mtime, hash) index to disk. Idempotent — a
        no-op when nothing changed since the last load."""
        if not self._mtime_dirty:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        _atomic_write(
            self.root / self._MTIME_INDEX_NAME,
            json.dumps(self._mtime_index),
        )
        self._mtime_dirty = False

    def _load_mtime_index(self) -> dict[str, list]:
        path = self.root / self._MTIME_INDEX_NAME
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def clear(self) -> None:
        if not self.root.exists():
            return
        for entry in self.root.iterdir():
            if entry.suffix == ".json":
                entry.unlink()
        self._mtime_index = {}
        self._mtime_dirty = False


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
