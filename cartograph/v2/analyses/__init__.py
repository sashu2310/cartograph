"""Higher-order analyses over AnalyzedGraph — the engineering-insight layer.

Each finding kind lives in its own private module (`_orm.py`, `_cycles.py`,
`_async_patterns.py`, `_routes.py`, `_chains.py`, `_dead.py`, `_impact.py`);
this package's public surface is re-exported here. The only analysis-
spanning code is the `AnalysisReport` bundle and `analyze()` — everything
else is one-finding-kind-per-file.

All outputs are frozen pydantic IRs. Pure functions, no I/O.
"""

from __future__ import annotations

from cartograph.v2.analyses._async_patterns import SyncInAsync, find_sync_in_async
from cartograph.v2.analyses._chains import LongCallChain, find_long_call_chains
from cartograph.v2.analyses._coverage import FunctionCoverage, find_coverage
from cartograph.v2.analyses._cycles import ImportCycle, find_import_cycles
from cartograph.v2.analyses._dead import DeadFunction, find_dead
from cartograph.v2.analyses._impact import (
    CallSiteImpact,
    ImportSiteImpact,
    RenameImpact,
    rename_impact,
)
from cartograph.v2.analyses._orm import (
    AsyncBoundaryCrossing,
    MixedOperation,
    ModelHotspot,
    NPlusOneCandidate,
    find_async_boundary_crossings,
    find_mixed_operations,
    find_model_hotspots,
    find_n_plus_one,
)
from cartograph.v2.analyses._routes import PathCollision, find_path_collisions
from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.base import IR


class AnalysisReport(IR):
    """Bundle of all analyses produced by `analyze()`."""

    n_plus_one: tuple[NPlusOneCandidate, ...]
    hotspots: tuple[ModelHotspot, ...]
    mixed_ops: tuple[MixedOperation, ...]
    boundary_crossings: tuple[AsyncBoundaryCrossing, ...]
    import_cycles: tuple[ImportCycle, ...] = ()
    sync_in_async: tuple[SyncInAsync, ...] = ()
    path_collisions: tuple[PathCollision, ...] = ()
    long_call_chains: tuple[LongCallChain, ...] = ()


def analyze(graph: AnalyzedGraph) -> AnalysisReport:
    """Run every analysis; return one bundled report."""
    return AnalysisReport(
        n_plus_one=tuple(find_n_plus_one(graph)),
        hotspots=tuple(find_model_hotspots(graph)),
        mixed_ops=tuple(find_mixed_operations(graph)),
        boundary_crossings=tuple(find_async_boundary_crossings(graph)),
        import_cycles=tuple(find_import_cycles(graph)),
        sync_in_async=tuple(find_sync_in_async(graph)),
        path_collisions=tuple(find_path_collisions(graph)),
        long_call_chains=tuple(find_long_call_chains(graph)),
    )


__all__ = [
    # orm
    "NPlusOneCandidate",
    "ModelHotspot",
    "MixedOperation",
    "AsyncBoundaryCrossing",
    "find_n_plus_one",
    "find_model_hotspots",
    "find_mixed_operations",
    "find_async_boundary_crossings",
    # cycles
    "ImportCycle",
    "find_import_cycles",
    # async patterns
    "SyncInAsync",
    "find_sync_in_async",
    # routes
    "PathCollision",
    "find_path_collisions",
    # chains
    "LongCallChain",
    "find_long_call_chains",
    # dead
    "DeadFunction",
    "find_dead",
    # coverage
    "FunctionCoverage",
    "find_coverage",
    # impact
    "CallSiteImpact",
    "ImportSiteImpact",
    "RenameImpact",
    "rename_impact",
    # bundle
    "AnalysisReport",
    "analyze",
]
