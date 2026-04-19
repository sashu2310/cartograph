"""FastAPI-backed DAG viewer. Mounts a Cytoscape.js SPA from cartograph/v2/web/static."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.stages.present.web_models import (
    CallersResponse,
    GraphResponse,
    LlmStatusResponse,
    NarrateResponse,
    OverviewResponse,
    SearchResponse,
)
from cartograph.v2.stages.present.web_serializers import (
    serialize_callers,
    serialize_graph_trace,
    serialize_overview,
    serialize_search,
)

OutputFormat = Literal["cli", "json", "html", "markdown", "mermaid", "dot"]

_STATIC_DIR = Path(__file__).resolve().parents[2] / "web" / "static"


class WebPresenter:
    name: str = "web"
    output_format: OutputFormat = "html"

    def render(self, _graph: AnalyzedGraph, _options: dict[str, Any]) -> bytes:
        """Return the static index.html. Client fetches data via the mounted API."""
        return (_STATIC_DIR / "index.html").read_bytes()


def build_app(graph: AnalyzedGraph, project_name: str = "cartograph") -> FastAPI:
    """Construct a FastAPI app bound to a single AnalyzedGraph.

    Serves the Cytoscape.js SPA at `/` and a JSON API at `/api/*` with
    OpenAPI docs at `/docs`. State lives in the closure — multiple apps can
    coexist in one process, bound to different graphs.
    """

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # No startup work today; the graph is already built in the CLI before
        # the server starts. Reserved for future async-initialized resources
        # (e.g. LLM client pools).
        yield

    app = FastAPI(
        title=f"Cartograph v2 — {project_name}",
        description="Deterministic call-graph API for probabilistic LLMs.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(str(_STATIC_DIR / "index.html"))

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        # Browsers request this automatically; return empty 204 to kill the
        # spurious 404 line in the access log.
        return Response(status_code=204)

    @app.get("/api/overview", response_model=OverviewResponse, tags=["graph"])
    def overview() -> dict[str, Any]:
        return serialize_overview(graph, project_name)

    @app.get("/api/graph/{qname:path}", response_model=GraphResponse, tags=["graph"])
    def subgraph(
        qname: str, depth: int = Query(default=5, ge=1, le=10)
    ) -> dict[str, Any]:
        if qname not in graph.annotated.resolved.functions:
            raise HTTPException(status_code=404, detail=f"unknown qname: {qname}")
        return serialize_graph_trace(graph, qname, depth)

    @app.get(
        "/api/callers/{qname:path}",
        response_model=CallersResponse,
        tags=["graph"],
    )
    def callers(qname: str) -> dict[str, Any]:
        if qname not in graph.annotated.resolved.functions:
            raise HTTPException(status_code=404, detail=f"unknown qname: {qname}")
        return serialize_callers(graph, qname)

    @app.get("/api/search", response_model=SearchResponse, tags=["graph"])
    def search(
        q: str = Query(default=""), limit: int = Query(default=20, ge=1, le=100)
    ) -> dict[str, Any]:
        if not q:
            return {"query": "", "results": []}
        return serialize_search(graph, q, limit)

    @app.get("/api/llm-status", response_model=LlmStatusResponse, tags=["llm"])
    def llm_status() -> dict[str, Any]:
        """Heuristic: one of the supported provider envs must be set.
        Actual model selection goes through CARTOGRAPH_LLM_MODEL."""
        available = bool(
            os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("CARTOGRAPH_LLM_MODEL", "").startswith("ollama:")
        )
        return {"available": available}

    @app.get(
        "/api/narrate/{qname:path}",
        response_model=NarrateResponse,
        tags=["llm"],
    )
    async def narrate(
        qname: str, depth: int = Query(default=4, ge=1, le=10)
    ) -> dict[str, Any]:
        if qname not in graph.annotated.resolved.functions:
            return {"error": f"unknown qname: {qname}"}
        try:
            from cartograph.v2.stages.present.llm import DEFAULT_MODEL, narrate_flow

            model = os.getenv("CARTOGRAPH_LLM_MODEL", DEFAULT_MODEL)
            text = await narrate_flow(graph, qname, depth=depth, model=model)
            return {"narrative": text, "model": model}
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    return app


def serve(
    graph: AnalyzedGraph,
    *,
    host: str = "127.0.0.1",
    port: int = 3333,
    project_name: str = "cartograph",
) -> None:
    """Run the live FastAPI server until interrupted. Blocks the caller."""
    import uvicorn

    app = build_app(graph, project_name=project_name)
    uvicorn.run(app, host=host, port=port, log_level="info")
