"""CARTOGRAPH web viewer — FastAPI application."""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from cartograph.graph.call_graph import CallGraph
from cartograph.graph.models import ProjectIndex
from cartograph.web.serializers import (
    serialize_callers,
    serialize_graph_trace,
    serialize_overview,
    serialize_search,
)

logger = logging.getLogger(__name__)

# Module-level state — populated by create_app()
_graph: CallGraph | None = None
_index: ProjectIndex | None = None
_project_name: str = ""
_entry_point_ids: set[str] = set()
_llm_provider = None

STATIC_DIR = Path(__file__).parent / "static"


class BlastRequest(BaseModel):
    files: list[str] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)
    depth: int = Field(default=10, ge=1, le=50)


def create_app(
    graph: CallGraph,
    index: ProjectIndex,
    project_name: str,
) -> FastAPI:
    """Create the FastAPI app with graph data loaded in memory."""
    global _graph, _index, _project_name, _entry_point_ids, _llm_provider
    _graph = graph
    _index = index
    _project_name = project_name
    _entry_point_ids = {ep.node_id for ep in index.entry_points}

    # Try to initialize LLM provider (optional — works without it)
    try:
        from cartograph.llm import get_llm_provider

        _llm_provider = get_llm_provider()
    except Exception:
        _llm_provider = None

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

    @app.get("/api/narrate/{qname:path}")
    async def narrate(qname: str, depth: int = Query(default=5, ge=1, le=10)):
        if not _llm_provider:
            return {
                "error": "LLM not configured. Set CARTOGRAPH_LLM_PROVIDER and API key.",
                "narrative": None,
            }
        if qname not in _graph.functions:
            return {"error": f"Function '{qname}' not found", "narrative": None}
        try:
            from cartograph.llm.narrator import narrate_flow

            response = narrate_flow(_graph, qname, _llm_provider, depth=depth)
            return {
                "narrative": response.content,
                "model": response.model,
                "usage": response.usage,
            }
        except Exception as e:
            logger.exception(f"LLM narration failed for {qname}")
            return {"error": str(e), "narrative": None}

    @app.get("/api/llm-status")
    async def llm_status():
        return {"available": _llm_provider is not None}

    @app.post("/api/blast")
    async def post_blast(payload: BlastRequest) -> dict:
        from cartograph.blast.analyzer import BlastAnalyzer, UnknownQnameError
        from cartograph.web.serializers import serialize_blast

        if not payload.files and not payload.functions:
            raise HTTPException(
                status_code=400,
                detail="Must provide at least one of: files, functions",
            )

        analyzer = BlastAnalyzer(graph=_graph, index=_index)

        try:
            if payload.functions:
                report = analyzer.analyze_functions(
                    list(payload.functions), max_depth=payload.depth
                )
            else:
                files = [Path(f) for f in payload.files]
                report = analyzer.analyze_files(files, max_depth=payload.depth)
        except UnknownQnameError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown function qname: {exc.qname}",
            ) from exc

        return serialize_blast(report)

    return app
