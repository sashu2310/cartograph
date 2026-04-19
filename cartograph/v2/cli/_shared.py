"""Cross-command helpers: path / qname resolution, pipeline build, cache footer."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import click

from cartograph.v2.config import DEFAULT_EXCLUDE_DIRS, RunConfig
from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.base import is_err
from cartograph.v2.pipeline import Pipeline
from cartograph.v2.stages.annotate.registry import default_annotators
from cartograph.v2.stages.discover.topology import TopologyDiscoverer
from cartograph.v2.stages.extract.treesitter_extractor import TreesitterExtractor
from cartograph.v2.stages.present.cli import CliPresenter
from cartograph.v2.stages.resolve.lsp.server import LspServer
from cartograph.v2.stages.resolve.ty_resolver import TyResolver

_LAST_PROJECT_FILE = Path.home() / ".cartograph" / "last_project_v2"


def resolve_qname(functions: dict, name: str) -> str | None:
    """Map a user-supplied name to a full qname: exact → suffix → substring.

    Matches v1's `_find_function` behaviour. First suffix hit and first
    substring hit win — no scoring, no ranking. Callers get `None` if
    nothing matches; `qname_suggestions()` supplies hints for the error.
    """
    if name in functions:
        return name
    for qn in functions:
        if qn.endswith(f".{name}"):
            return qn
    needle = name.lower()
    for qn in functions:
        if needle in qn.lower():
            return qn
    return None


def qname_suggestions(functions: dict, name: str, n: int = 5) -> list[str]:
    """Top-n substring-matching qnames, for 'did you mean' messages."""
    needle = name.lower()
    return [qn for qn in functions if needle in qn.lower()][:n]


def require_qname(functions: dict, name: str) -> str:
    """Resolve or raise ClickException with suggestions."""
    resolved = resolve_qname(functions, name)
    if resolved is not None:
        return resolved
    hints = qname_suggestions(functions, name)
    hint_block = "\n  ".join(hints) if hints else "(no similar names found)"
    raise click.ClickException(f"unknown qname: {name}\ndid you mean:\n  {hint_block}")


def save_last_project(path: Path) -> None:
    _LAST_PROJECT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LAST_PROJECT_FILE.write_text(str(path.resolve()))


def get_last_project() -> Path | None:
    if not _LAST_PROJECT_FILE.exists():
        return None
    candidate = Path(_LAST_PROJECT_FILE.read_text().strip())
    return candidate if candidate.exists() else None


def resolve_path(path: Path | None) -> Path:
    """Use the given path if provided; otherwise fall back to the last `init`-ed project."""
    if path is not None:
        return path.resolve()
    last = get_last_project()
    if last is None:
        raise click.ClickException(
            "no project path given and no previous `init` found. "
            "run: carto2 init /path/to/project"
        )
    click.echo(f"(using last project: {last})", err=True)
    return last


def parse_exclude_dirs(spec: str | None) -> frozenset[str] | None:
    """Parse `--exclude-dirs foo,bar,baz` into a frozenset. Empty → None."""
    if not spec:
        return None
    return frozenset(part.strip() for part in spec.split(",") if part.strip())


def _build_pipeline(server: LspServer) -> Pipeline:
    return Pipeline(
        extractor=TreesitterExtractor(),
        resolver=TyResolver(server=server),
        annotators=default_annotators(),
        discoverer=TopologyDiscoverer(),
        presenter=CliPresenter(),
    )


async def _build_graph_async(
    path: Path,
    include_tests: bool,
    extra_exclude: frozenset[str] | None = None,
) -> AnalyzedGraph:
    stats: dict[str, Any] = {}
    start = time.perf_counter()
    exclude = DEFAULT_EXCLUDE_DIRS | (extra_exclude or frozenset())
    async with LspServer(["ty", "server"]) as server:
        pipeline = _build_pipeline(server)
        result = await pipeline.build(
            RunConfig(
                project_root=path,
                include_tests=include_tests,
                exclude_dirs=exclude,
            ),
            stats=stats,
        )
    elapsed = time.perf_counter() - start
    if is_err(result):
        raise click.ClickException(f"pipeline failed: {result.error}")
    print_cache_footer(stats, elapsed)
    # is_err narrowed the union above; ty's TypeGuard inference is imperfect
    # here, so explicit assert + attribute access preserves correctness.
    assert not is_err(result)
    return result.value


def build_graph(
    path: Path,
    include_tests: bool,
    extra_exclude: frozenset[str] | None = None,
) -> AnalyzedGraph:
    """Synchronous convenience wrapper — the shape every command wants."""
    return asyncio.run(_build_graph_async(path, include_tests, extra_exclude))


def print_cache_footer(stats: dict, elapsed: float) -> None:
    """Single-line cache + timing summary on stderr.

    Format: `(2.4s · resolve: hit · extract: 42/42 hit)`
    On stderr so it never contaminates pipes like `carto2 context | claude`.
    """
    parts = [f"{elapsed:.2f}s"]
    resolve_hit = stats.get("resolve_cache_hit")
    if resolve_hit is True:
        parts.append("[green]resolve: hit[/]")
    elif resolve_hit is False:
        parts.append("[yellow]resolve: miss[/]")
    extract_hits = stats.get("extract_hits", 0) or 0
    extract_misses = stats.get("extract_misses", 0) or 0
    total = extract_hits + extract_misses
    if total > 0:
        parts.append(f"extract: {extract_hits}/{total} hit")
    from rich.console import Console

    Console(stderr=True).print(f"[dim]({' · '.join(parts)})[/]")
