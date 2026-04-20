"""AnalyzedGraph → JSON shapes the Cytoscape SPA expects."""

from __future__ import annotations

from typing import Any

from cartograph.v2.ir.analyzed import (
    AnalyzedGraph,
    ApiRouteEntry,
    CeleryTaskEntry,
    DiscoveredEntry,
    EntryPoint,
    SignalHandlerEntry,
)
from cartograph.v2.ir.resolved import Edge, FunctionRef, ResolvedGraph


def serialize_overview(graph: AnalyzedGraph, project_name: str) -> dict[str, Any]:
    from cartograph.v2.stages.present.util import bucket_unresolved

    resolved = graph.annotated.resolved
    entry_points_by_type: dict[str, list[dict[str, Any]]] = {}
    for ep in graph.entry_points:
        entry_points_by_type.setdefault(ep.kind, []).append(_entry_json(ep))
    modules = {f.module for f in resolved.functions.values()}
    class_count = sum(1 for fn in resolved.functions.values() if fn.kind == "class")
    return {
        "project_name": project_name,
        "stats": {
            "total_modules": len(modules),
            "total_functions": len(resolved.functions),
            "total_classes": class_count,
            "total_edges": len(resolved.edges),
            "total_unresolved": len(resolved.unresolved),
            "unresolved_by_reason": bucket_unresolved(resolved.unresolved),
            "total_entry_points": len(graph.entry_points),
        },
        "entry_points_by_type": entry_points_by_type,
    }


def serialize_graph_trace(
    graph: AnalyzedGraph, root_qname: str, depth: int
) -> dict[str, Any]:
    resolved = graph.annotated.resolved
    nodes: dict[str, dict[str, Any]] = {}
    edges_out: list[dict[str, Any]] = []
    visited: set[str] = set()

    def add_node(qname: str) -> None:
        if qname in nodes:
            return
        func = resolved.functions.get(qname)
        if func is None:
            return
        nodes[qname] = _function_json(func, resolved)

    def walk(qname: str, d: int) -> None:
        if d <= 0 or qname in visited:
            return
        visited.add(qname)
        add_node(qname)
        for edge in resolved.get_callees(qname):
            add_node(edge.callee_qname)
            edges_out.append(_edge_json(edge, resolved))
            walk(edge.callee_qname, d - 1)

    walk(root_qname, depth)

    for qname, node in nodes.items():
        callees = resolved.get_callees(qname)
        expanded = {e["target"] for e in edges_out if e["source"] == qname}
        node["expandable"] = any(
            e.callee_qname not in expanded or e.callee_qname not in nodes
            for e in callees
            if e.callee_qname in resolved.functions
        )

    files_touched = list({n["file"] for n in nodes.values()})
    return {
        "entry_point": root_qname,
        "nodes": nodes,
        "edges": edges_out,
        "metadata": {
            "total_nodes": len(nodes),
            "total_edges": len(edges_out),
            "files_touched": files_touched,
            "total_files": len(files_touched),
            "async_boundaries": sum(
                1 for e in edges_out if e["type"] == "async_dispatch"
            ),
        },
    }


def serialize_callers(graph: AnalyzedGraph, qname: str) -> dict[str, Any]:
    resolved = graph.annotated.resolved
    callers: list[dict[str, Any]] = []
    for edge in resolved.get_callers(qname):
        caller = resolved.functions.get(edge.caller_qname)
        if caller is None:
            continue
        callee = resolved.functions.get(qname)
        callers.append(
            {
                "qualified_name": caller.qname,
                "name": caller.name,
                "file": str(caller.source_path),
                "line_start": caller.line_start,
                "type": caller.kind,
                "is_cross_file": (
                    callee is not None and caller.source_path != callee.source_path
                ),
            }
        )
    return {"target": qname, "callers": callers}


def serialize_search(
    graph: AnalyzedGraph, query: str, limit: int = 20
) -> dict[str, Any]:
    from cartograph.v2.stages.present.util import ranked_search

    resolved = graph.annotated.resolved
    entry_qnames = {ep.qname for ep in graph.entry_points}
    results: list[dict[str, Any]] = []
    for _, qname in ranked_search(resolved, query, limit):
        func = resolved.functions[qname]
        results.append(
            {
                "qualified_name": qname,
                "name": func.name,
                "file": str(func.source_path),
                "type": func.kind,
                "is_entry_point": qname in entry_qnames,
            }
        )
    return {"query": query, "results": results}


def _entry_json(ep: EntryPoint) -> dict[str, Any]:
    module = ep.qname.rsplit(".", 1)[0] if "." in ep.qname else ""
    if isinstance(ep, DiscoveredEntry):
        trigger = f"@{ep.trigger_decorator}"
    elif isinstance(ep, ApiRouteEntry):
        trigger = f"{ep.method} {ep.path}"
    elif isinstance(ep, CeleryTaskEntry):
        trigger = ep.queue or ""
    elif isinstance(ep, SignalHandlerEntry):
        trigger = ep.signal_name
    else:
        trigger = ""
    return {
        "node_id": ep.qname,
        "type": ep.kind,
        "trigger": trigger,
        "description": ep.description,
        "module": module,
    }


def _function_json(func: FunctionRef, resolved: ResolvedGraph) -> dict[str, Any]:
    return {
        "name": func.name,
        "qualified_name": func.qname,
        "file": str(func.source_path),
        "line_start": func.line_start,
        "line_end": func.line_end,
        "type": func.kind,
        "decorators": list(func.decorators),
        "docstring": func.docstring or "",
        "annotations": {},  # filled per-label by consumers if needed
        "has_callees": len(resolved.get_callees(func.qname)) > 0,
        "branches": [],  # v2 encodes conditions on edges, not per-function branches
    }


def _edge_json(edge: Edge, resolved: ResolvedGraph) -> dict[str, Any]:
    caller = resolved.functions.get(edge.caller_qname)
    callee = resolved.functions.get(edge.callee_qname)
    is_cross_file = (
        caller is not None
        and callee is not None
        and caller.source_path != callee.source_path
    )
    return {
        "source": edge.caller_qname,
        "target": edge.callee_qname,
        "type": "async_dispatch" if edge.async_kind else "calls",
        "async_type": edge.async_kind,
        "is_cross_file": is_cross_file,
        "line": edge.line,
        "condition": edge.condition,
    }
