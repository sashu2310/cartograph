"""Persistent cache — saves parsed index + call graph to .cartograph/ as JSON.

First scan is slow (parses everything). Subsequent commands load from cache.
Invalidation via file hashes — if a file changed, re-parse it.
"""

import json
from dataclasses import asdict
from pathlib import Path

from cartograph.graph.call_graph import CallEdge, CallGraph
from cartograph.graph.models import (
    ConditionalBranch,
    EntryPoint,
    EntryPointType,
    FunctionCall,
    NodeType,
    ParsedClass,
    ParsedFunction,
    ParsedImport,
    ParsedModule,
    ProjectIndex,
)

CACHE_VERSION = 2
INDEX_FILE = "index.json"
GRAPH_FILE = "graph.json"
META_FILE = "meta.json"


def save_cache(cache_dir: str, index: ProjectIndex, graph: CallGraph) -> None:
    """Save parsed index and call graph to cache directory."""
    path = Path(cache_dir)
    path.mkdir(parents=True, exist_ok=True)

    # Meta
    meta = {"version": CACHE_VERSION, "root_path": index.root_path}
    (path / META_FILE).write_text(json.dumps(meta), encoding="utf-8")

    # Index
    index_data = {
        "root_path": index.root_path,
        "modules": {mp: _serialize_module(m) for mp, m in index.modules.items()},
        "entry_points": [_serialize_entry_point(ep) for ep in index.entry_points],
    }
    (path / INDEX_FILE).write_text(
        json.dumps(index_data, default=str), encoding="utf-8"
    )

    # Graph
    graph_data = {
        "edges": [_serialize_edge(e) for e in graph.edges],
        "unresolved_count": graph.total_unresolved,
    }
    (path / GRAPH_FILE).write_text(
        json.dumps(graph_data, default=str), encoding="utf-8"
    )


def load_cache(cache_dir: str) -> tuple[ProjectIndex, CallGraph] | None:
    """Load index and call graph from cache. Returns None if cache is invalid."""
    path = Path(cache_dir)

    meta_path = path / META_FILE
    if not meta_path.exists():
        return None

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("version") != CACHE_VERSION:
            return None

        index_data = json.loads((path / INDEX_FILE).read_text(encoding="utf-8"))
        graph_data = json.loads((path / GRAPH_FILE).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    # Rebuild index
    index = ProjectIndex(root_path=index_data["root_path"])
    for mp, mdata in index_data["modules"].items():
        index.modules[mp] = _deserialize_module(mdata)
    for ep_data in index_data["entry_points"]:
        index.entry_points.append(_deserialize_entry_point(ep_data))

    # Rebuild graph — functions from index, edges from graph file
    graph = CallGraph()
    for module in index.modules.values():
        for func in module.functions:
            graph.functions[func.qualified_name] = func
    for edge_data in graph_data["edges"]:
        graph.edges.append(_deserialize_edge(edge_data))

    return index, graph


def is_cache_fresh(
    cache_dir: str,
    root_path: str,
    exclude_dirs: "set[str] | list[str] | None" = None,
) -> bool:
    """Check if cache is fresher than every Python source file in the project.

    Compares each .py file's mtime against the cache index's mtime. If any
    source file is newer than the cache, or if any new .py file has appeared
    since the cache was written, the cache is stale.

    mtime is sufficient in practice: editor saves, git checkout/pull, and all
    normal file operations update mtime. The tradeoff against hash-based
    verification is speed — stat() is microseconds per file vs. reading and
    hashing the file.
    """
    path = Path(cache_dir)
    cache_file = path / INDEX_FILE
    if not cache_file.exists():
        return False

    cache_mtime = cache_file.stat().st_mtime
    exclude = set(exclude_dirs or [])
    root = Path(root_path)

    for source_file in root.rglob("*.py"):
        if exclude and any(part in exclude for part in source_file.parts):
            continue
        try:
            if source_file.stat().st_mtime > cache_mtime:
                return False
        except OSError:
            return False

    return True


# ── Serialization helpers ─────────────────────────────────


def _serialize_module(m: ParsedModule) -> dict:
    return {
        "file_path": m.file_path,
        "module_path": m.module_path,
        "functions": [_serialize_function(f) for f in m.functions],
        "classes": m.classes,
        "imports": [asdict(imp) for imp in m.imports],
        "file_hash": m.file_hash,
        "module_types": m.module_types,
        "parsed_classes": {name: asdict(cls) for name, cls in m.parsed_classes.items()},
    }


def _serialize_function(f: ParsedFunction) -> dict:
    return {
        "name": f.name,
        "qualified_name": f.qualified_name,
        "file_path": f.file_path,
        "line_start": f.line_start,
        "line_end": f.line_end,
        "type": f.type.value,
        "docstring": f.docstring,
        "decorators": f.decorators,
        "decorator_details": f.decorator_details,
        "calls": [_serialize_call(c) for c in f.calls],
        "branches": [_serialize_branch(b) for b in f.branches],
        "class_name": f.class_name,
        "module_path": f.module_path,
        "local_types": f.local_types,
        "parameter_types": f.parameter_types,
        "return_type": f.return_type,
        "call_assignments": f.call_assignments,
    }


def _serialize_call(c: FunctionCall) -> dict:
    return {
        "name": c.name,
        "qualified_name": c.qualified_name,
        "line": c.line,
        "is_method_call": c.is_method_call,
        "receiver": c.receiver,
        "args_count": c.args_count,
        "is_async_dispatch": c.is_async_dispatch,
        "async_type": c.async_type.value if c.async_type else None,
    }


def _serialize_branch(b: ConditionalBranch) -> dict:
    return {
        "condition": b.condition,
        "line": b.line,
        "calls": [_serialize_call(c) for c in b.calls],
        "is_else": b.is_else,
    }


def _serialize_entry_point(ep: EntryPoint) -> dict:
    return {
        "node_id": ep.node_id,
        "type": ep.type.value,
        "trigger": ep.trigger,
        "description": ep.description,
    }


def _serialize_edge(e: CallEdge) -> dict:
    return {
        "caller": e.caller,
        "callee": e.callee,
        "is_cross_file": e.is_cross_file,
        "condition": e.condition,
        "call_name": e.call.name,
        "call_line": e.call.line,
        "call_is_method": e.call.is_method_call,
        "call_receiver": e.call.receiver,
        "call_is_async": e.call.is_async_dispatch,
        "call_async_type": e.call.async_type.value if e.call.async_type else None,
        "call_args_count": e.call.args_count,
    }


# ── Deserialization helpers ───────────────────────────────


def _deserialize_module(data: dict) -> ParsedModule:
    functions = [_deserialize_function(f) for f in data["functions"]]
    imports = [ParsedImport(**imp) for imp in data["imports"]]
    parsed_classes = {
        name: ParsedClass(**cls) for name, cls in data.get("parsed_classes", {}).items()
    }
    return ParsedModule(
        file_path=data["file_path"],
        module_path=data["module_path"],
        functions=functions,
        classes=data["classes"],
        imports=imports,
        file_hash=data.get("file_hash"),
        module_types=data.get("module_types", {}),
        parsed_classes=parsed_classes,
    )


def _deserialize_function(data: dict) -> ParsedFunction:
    calls = [_deserialize_call(c) for c in data.get("calls", [])]
    branches = [_deserialize_branch(b) for b in data.get("branches", [])]
    return ParsedFunction(
        name=data["name"],
        qualified_name=data["qualified_name"],
        file_path=data["file_path"],
        line_start=data["line_start"],
        line_end=data["line_end"],
        type=NodeType(data["type"]),
        docstring=data.get("docstring"),
        decorators=data.get("decorators", []),
        decorator_details=data.get("decorator_details", []),
        calls=calls,
        branches=branches,
        class_name=data.get("class_name"),
        module_path=data.get("module_path"),
        local_types=data.get("local_types", {}),
        parameter_types=data.get("parameter_types", {}),
        return_type=data.get("return_type"),
        call_assignments=data.get("call_assignments", {}),
    )


def _deserialize_call(data: dict) -> FunctionCall:
    async_type = None
    if data.get("async_type"):
        from cartograph.graph.models import AsyncBoundaryType

        async_type = AsyncBoundaryType(data["async_type"])
    return FunctionCall(
        name=data["name"],
        qualified_name=data.get("qualified_name"),
        line=data.get("line", 0),
        is_method_call=data.get("is_method_call", False),
        receiver=data.get("receiver"),
        args_count=data.get("args_count", 0),
        is_async_dispatch=data.get("is_async_dispatch", False),
        async_type=async_type,
    )


def _deserialize_branch(data: dict) -> ConditionalBranch:
    calls = [_deserialize_call(c) for c in data.get("calls", [])]
    return ConditionalBranch(
        condition=data.get("condition"),
        line=data.get("line", 0),
        calls=calls,
        is_else=data.get("is_else", False),
    )


def _deserialize_entry_point(data: dict) -> EntryPoint:
    return EntryPoint(
        node_id=data["node_id"],
        type=EntryPointType(data["type"]),
        trigger=data["trigger"],
        description=data.get("description"),
    )


def _deserialize_edge(data: dict) -> CallEdge:
    async_type = None
    if data.get("call_async_type"):
        from cartograph.graph.models import AsyncBoundaryType

        async_type = AsyncBoundaryType(data["call_async_type"])
    call = FunctionCall(
        name=data.get("call_name", ""),
        line=data.get("call_line", 0),
        is_method_call=data.get("call_is_method", False),
        receiver=data.get("call_receiver"),
        is_async_dispatch=data.get("call_is_async", False),
        async_type=async_type,
    )
    return CallEdge(
        caller=data["caller"],
        callee=data["callee"],
        call=call,
        is_cross_file=data.get("is_cross_file", False),
        condition=data.get("condition"),
    )
