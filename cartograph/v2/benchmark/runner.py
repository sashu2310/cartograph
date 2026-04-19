"""Per-target benchmark runners. Each produces a BenchmarkResult with timing + graph."""

from __future__ import annotations

import platform
import resource
import subprocess
import time
from pathlib import Path

from cartograph.config import CartographConfig
from cartograph.core import parse_and_build
from cartograph.v2.benchmark.adapters.v1_to_common import v1_to_common
from cartograph.v2.benchmark.adapters.v2_to_common import v2_to_common
from cartograph.v2.benchmark.metrics import BenchmarkResult, Target
from cartograph.v2.config import RunConfig
from cartograph.v2.ir.base import Err_
from cartograph.v2.pipeline import Pipeline
from cartograph.v2.stages.discover.topology import TopologyDiscoverer
from cartograph.v2.stages.extract.treesitter_extractor import TreesitterExtractor
from cartograph.v2.stages.present.cli import CliPresenter
from cartograph.v2.stages.resolve.lsp.server import LspServer
from cartograph.v2.stages.resolve.ty_resolver import TyResolver


def _peak_memory_mb() -> float:
    """Current process's peak RSS in MB. Linux reports KB, macOS reports bytes."""
    ru = resource.getrusage(resource.RUSAGE_SELF)
    if platform.system() == "Darwin":
        return ru.ru_maxrss / (1024 * 1024)
    return ru.ru_maxrss / 1024  # Linux: KB → MB


def _project_commit(project_root: Path) -> str | None:
    """Short git SHA or None if not a git repo / git not available."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def run_v1(project_root: Path, project_name: str) -> BenchmarkResult:
    """Run the legacy v1 pipeline and capture a BenchmarkResult."""
    commit = _project_commit(project_root)
    config = CartographConfig(root_path=str(project_root))

    start = time.perf_counter()
    index, graph = parse_and_build(config, use_cache=False)
    elapsed = time.perf_counter() - start

    total_sites = sum(
        len(fn.calls) for m in index.modules.values() for fn in m.functions
    ) + sum(
        len(branch.calls)
        for m in index.modules.values()
        for fn in m.functions
        for branch in fn.branches
    )

    common = v1_to_common(
        index, graph, project_name=project_name, project_commit=commit
    )

    return BenchmarkResult(
        target="v1",
        project_name=project_name,
        project_commit=commit,
        version="v1",
        total_call_sites=total_sites,
        resolved_count=graph.total_resolved,
        unresolved_count=graph.total_unresolved,
        wall_time_s=elapsed,
        peak_memory_mb=_peak_memory_mb(),
        graph=common,
    )


async def run_v2_ty(project_root: Path, project_name: str) -> BenchmarkResult:
    """Run the v2 pipeline (ty + treesitter) and capture a BenchmarkResult."""
    commit = _project_commit(project_root)

    start = time.perf_counter()
    async with LspServer(["ty", "server"]) as server:
        pipeline = Pipeline(
            extractor=TreesitterExtractor(),
            resolver=TyResolver(server=server),
            annotators=(),
            discoverer=TopologyDiscoverer(),
            presenter=CliPresenter(),
        )
        built = await pipeline.build(RunConfig(project_root=project_root))
    elapsed = time.perf_counter() - start

    if isinstance(built, Err_):
        raise RuntimeError(f"v2-ty pipeline failed: {built.error}")

    analyzed = built.value
    resolved = analyzed.annotated.resolved
    total_sites = len(resolved.edges) + len(resolved.unresolved)

    common = v2_to_common(
        analyzed,
        project_name=project_name,
        producer="v2-ty",
        project_commit=commit,
    )

    return BenchmarkResult(
        target="v2-ty",
        project_name=project_name,
        project_commit=commit,
        version=TyResolver.version,
        total_call_sites=total_sites,
        resolved_count=len(resolved.edges),
        unresolved_count=len(resolved.unresolved),
        wall_time_s=elapsed,
        peak_memory_mb=_peak_memory_mb(),
        graph=common,
    )


async def run_target(
    target: Target, project_root: Path, project_name: str
) -> BenchmarkResult:
    """Dispatch to the right runner by target name."""
    if target == "v1":
        return run_v1(project_root, project_name)
    if target == "v2-ty":
        return await run_v2_ty(project_root, project_name)
    raise ValueError(f"unknown target {target!r}; valid: 'v1', 'v2-ty'")
