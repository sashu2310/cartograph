"""CARTOGRAPH web viewer — FastAPI application."""

from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from cartograph.graph.call_graph import CallGraph
from cartograph.graph.models import ProjectIndex
from cartograph.web.serializers import (
    serialize_callers,
    serialize_graph_trace,
    serialize_overview,
    serialize_search,
)

# Module-level state — populated by create_app()
_graph: CallGraph | None = None
_index: ProjectIndex | None = None
_project_name: str = ""
_entry_point_ids: set[str] = set()

STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    graph: CallGraph,
    index: ProjectIndex,
    project_name: str,
) -> FastAPI:
    """Create the FastAPI app with graph data loaded in memory."""
    global _graph, _index, _project_name, _entry_point_ids
    _graph = graph
    _index = index
    _project_name = project_name
    _entry_point_ids = {ep.node_id for ep in index.entry_points}

    app = FastAPI(title=f"CARTOGRAPH — {project_name}")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(str(STATIC_DIR / "index.html"))

    @app.get("/api/overview")
    async def overview():
        return serialize_overview(_index, _graph, _project_name)

    @app.get("/api/graph/{qname:path}")
    async def graph_trace(qname: str, depth: int = Query(default=5, ge=1, le=10)):
        if qname.endswith("/callers"):
            # Handle /api/graph/{qname}/callers
            actual_qname = qname.rsplit("/callers", 1)[0]
            return serialize_callers(_graph, actual_qname)
        if qname not in _graph.functions:
            return {"error": f"Function '{qname}' not found", "nodes": {}, "edges": []}
        return serialize_graph_trace(_graph, qname, depth)

    @app.get("/api/callers/{qname:path}")
    async def callers(qname: str):
        return serialize_callers(_graph, qname)

    @app.get("/api/search")
    async def search(
        q: str = Query(default=""), limit: int = Query(default=20, le=100)
    ):
        if not q:
            return {"query": "", "results": []}
        result = serialize_search(_graph, q, limit)
        # Enrich with entry point info
        for r in result["results"]:
            r["is_entry_point"] = r["qualified_name"] in _entry_point_ids
        return result

    return app
