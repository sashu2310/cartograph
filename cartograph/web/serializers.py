"""Graph → JSON serializers for the web API."""

from cartograph.graph.call_graph import CallGraph
from cartograph.graph.models import ProjectIndex


def serialize_overview(
    index: ProjectIndex, graph: CallGraph, project_name: str
) -> dict:
    """Serialize project overview for the sidebar."""
    entry_points_by_type: dict[str, list] = {}
    for ep in index.entry_points:
        type_key = ep.type.value
        if type_key not in entry_points_by_type:
            entry_points_by_type[type_key] = []
        entry_points_by_type[type_key].append(
            {
                "node_id": ep.node_id,
                "type": type_key,
                "trigger": ep.trigger,
                "description": ep.description,
                "module": ep.node_id.rsplit(".", 1)[0] if "." in ep.node_id else "",
            }
        )

    return {
        "project_name": project_name,
        "stats": {
            "total_modules": index.total_modules,
            "total_functions": index.total_functions,
            "total_edges": graph.total_resolved,
            "total_unresolved": graph.total_unresolved,
            "total_entry_points": len(index.entry_points),
        },
        "entry_points_by_type": entry_points_by_type,
    }


def serialize_graph_trace(graph: CallGraph, root_qname: str, depth: int) -> dict:
    """Serialize a call graph trace to JSON for DAG rendering."""
    nodes = {}
    edges = []
    visited: set[str] = set()

    def _add_node(qname: str):
        """Add a function to the nodes dict if it exists."""
        if qname in nodes:
            return
        func = graph.functions.get(qname)
        if func:
            branches = []
            for b in func.branches:
                branch_calls = [c.name for c in b.calls]
                branches.append(
                    {
                        "condition": b.condition,
                        "line": b.line,
                        "calls": branch_calls,
                        "is_else": b.is_else,
                    }
                )
            nodes[qname] = {
                "name": func.name,
                "qualified_name": func.qualified_name,
                "file": func.file_path,
                "line_start": func.line_start,
                "line_end": func.line_end,
                "type": func.type.value,
                "decorators": func.decorators,
                "docstring": func.docstring,
                "annotations": func.annotations,
                "has_callees": len(graph.get_callees(qname)) > 0,
                "branches": branches,
            }

    def _walk(qname: str, d: int):
        if d <= 0 or qname in visited:
            return
        visited.add(qname)
        _add_node(qname)

        for edge in graph.get_callees(qname):
            # Always add callee as a node — even at depth boundary
            _add_node(edge.callee)
            edges.append(
                {
                    "source": edge.caller,
                    "target": edge.callee,
                    "type": "async_dispatch"
                    if edge.call.is_async_dispatch
                    else "calls",
                    "async_type": edge.call.async_type.value
                    if edge.call.async_type
                    else None,
                    "is_cross_file": edge.is_cross_file,
                    "line": edge.call.line,
                    "condition": edge.condition,
                }
            )
            _walk(edge.callee, d - 1)

    _walk(root_qname, depth)

    files_touched = list({n["file"] for n in nodes.values()})

    # Mark leaf nodes that have unexpanded children
    for qname, node in nodes.items():
        callees = graph.get_callees(qname)
        expanded_targets = {e["target"] for e in edges if e["source"] == qname}
        node["expandable"] = any(
            e.callee not in expanded_targets or e.callee not in nodes
            for e in callees
            if e.callee in graph.functions
        )

    return {
        "entry_point": root_qname,
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "files_touched": files_touched,
            "total_files": len(files_touched),
            "async_boundaries": len(
                [e for e in edges if e["type"] == "async_dispatch"]
            ),
        },
    }


def serialize_callers(graph: CallGraph, qname: str) -> dict:
    """Serialize callers of a function for the detail panel."""
    callers = []
    for edge in graph.get_callers(qname):
        func = graph.functions.get(edge.caller)
        if func:
            callers.append(
                {
                    "qualified_name": func.qualified_name,
                    "name": func.name,
                    "file": func.file_path,
                    "line_start": func.line_start,
                    "type": func.type.value,
                    "is_cross_file": edge.is_cross_file,
                }
            )
    return {"target": qname, "callers": callers}


def serialize_search(graph: CallGraph, query: str, limit: int = 20) -> dict:
    """Search functions by name (prefix/substring match)."""
    query_lower = query.lower()
    results = []
    # Check entry point node IDs for fast lookup
    entry_point_ids: set[str] = set()

    for qname, func in graph.functions.items():
        if query_lower in qname.lower() or query_lower in func.name.lower():
            results.append(
                {
                    "qualified_name": qname,
                    "name": func.name,
                    "file": func.file_path,
                    "type": func.type.value,
                    "is_entry_point": qname in entry_point_ids,
                }
            )
            if len(results) >= limit:
                break

    return {"query": query, "results": results}
