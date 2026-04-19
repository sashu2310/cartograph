"""Adapter: v2's AnalyzedGraph → CommonGraph.

Mirrors v1_to_common so the benchmark harness can diff v1 and v2 outputs
edge-for-edge under the same vocabulary. CommonGraph is deliberately lossy
(ADR-012) — branch conditions, typed labels, and variant-specific metadata
all collapse to the minimum needed for set-based comparison.
"""

from __future__ import annotations

from cartograph.v2.ir.analyzed import (
    AnalyzedGraph,
    ApiRouteEntry,
    CeleryTaskEntry,
    DiscoveredEntry,
    EntryPoint,
    SignalHandlerEntry,
)
from cartograph.v2.ir.common import (
    CommonEdge,
    CommonEntryPoint,
    CommonFunction,
    CommonGraph,
)


def v2_to_common(
    analyzed: AnalyzedGraph,
    project_name: str,
    *,
    producer: str = "v2-ty",
    project_commit: str | None = None,
) -> CommonGraph:
    """Convert an AnalyzedGraph into a CommonGraph for benchmarking."""
    resolved = analyzed.annotated.resolved

    functions: dict[str, CommonFunction] = {
        qname: CommonFunction(
            qname=ref.qname,
            module=ref.module,
            name=ref.name,
            line=ref.line_start,
            decorators=ref.decorators,
        )
        for qname, ref in resolved.functions.items()
    }

    edges: tuple[CommonEdge, ...] = tuple(
        CommonEdge(caller=e.caller_qname, callee=e.callee_qname, line=e.line)
        for e in resolved.edges
    )

    entry_points: tuple[CommonEntryPoint, ...] = tuple(
        CommonEntryPoint(
            qname=ep.qname,
            kind=ep.kind,
            trigger=_format_trigger(ep),
        )
        for ep in analyzed.entry_points
    )

    return CommonGraph(
        project_name=project_name,
        project_commit=project_commit,
        producer=producer,
        functions=functions,
        edges=edges,
        entry_points=entry_points,
    )


def _format_trigger(ep: EntryPoint) -> str | None:
    """Human-readable trigger string per entry kind — useful for diffing
    reports but not structurally compared."""
    if isinstance(ep, DiscoveredEntry):
        return f"@{ep.trigger_decorator}"
    if isinstance(ep, ApiRouteEntry):
        return f"{ep.method} {ep.path}"
    if isinstance(ep, CeleryTaskEntry):
        return f"celery_task[{ep.queue}]" if ep.queue else "celery_task"
    if isinstance(ep, SignalHandlerEntry):
        sender = f" from {ep.sender}" if ep.sender else ""
        return f"signal {ep.signal_name}{sender}"
    return None
