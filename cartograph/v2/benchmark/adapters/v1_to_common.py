"""Adapter: v1's (ProjectIndex, CallGraph) → v2 CommonGraph.

This lets the benchmark harness produce CommonGraphs from v1 runs before any
v2 stage is implemented. Once v2 has a matching `v2_to_common` adapter, the
harness can diff `v1_to_common(...)` against `v2_to_common(...)` on the same
project and produce a ComparisonReport.
"""

from __future__ import annotations

from cartograph.graph.call_graph import CallGraph
from cartograph.graph.models import EntryPointType, ProjectIndex
from cartograph.v2.ir.common import (
    CommonEdge,
    CommonEntryPoint,
    CommonFunction,
    CommonGraph,
)

# v1's EntryPointType enum values mapped to CommonGraph's shared vocabulary.
# Shared vocabulary is intentionally a subset of what each producer knows —
# richer labels live in AnalyzedGraph, not here.
_V1_KIND_MAP: dict[EntryPointType, str] = {
    EntryPointType.API_ROUTE: "api_route",
    EntryPointType.CELERY_TASK: "celery_task",
    EntryPointType.CELERY_BEAT: "celery_beat",
    EntryPointType.MANAGEMENT_COMMAND: "management_command",
    EntryPointType.SIGNAL_HANDLER: "signal_handler",
    EntryPointType.DISCOVERED: "discovered",
}


def v1_to_common(
    index: ProjectIndex,
    graph: CallGraph,
    project_name: str,
    project_commit: str | None = None,
) -> CommonGraph:
    """Produce a CommonGraph from a completed v1 scan.

    Pure function: given the same inputs, returns the same CommonGraph.
    """
    functions: dict[str, CommonFunction] = {}
    for module in index.modules.values():
        for func in module.functions:
            functions[func.qualified_name] = CommonFunction(
                qname=func.qualified_name,
                module=func.module_path or module.module_path,
                name=func.name,
                line=func.line_start,
                decorators=tuple(func.decorators),
            )

    edges: tuple[CommonEdge, ...] = tuple(
        CommonEdge(
            caller=e.caller,
            callee=e.callee,
            line=e.call.line if e.call else 0,
        )
        for e in graph.edges
    )

    entry_points: tuple[CommonEntryPoint, ...] = tuple(
        CommonEntryPoint(
            qname=ep.node_id,
            kind=_V1_KIND_MAP.get(ep.type, ep.type.value),
            trigger=ep.trigger,
        )
        for ep in index.entry_points
    )

    return CommonGraph(
        project_name=project_name,
        project_commit=project_commit,
        producer="v1",
        functions=functions,
        edges=edges,
        entry_points=entry_points,
    )
