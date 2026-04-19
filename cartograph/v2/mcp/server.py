"""MCP server exposing the v2 pipeline as agent-native tools.

One FastMCP instance per project root. The AnalyzedGraph is built lazily on
first tool call and cached for the server's lifetime — MCP hosts restart the
server to pick up file changes, so long-lived caching is correct.

Tools skew deterministic: `context` returns markdown facts for LLM reasoning,
`trace` / `callers` / `search` return structured JSON. No LLM narration tool
is exposed — narration is the caller's job.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from cartograph.v2.analyses import analyze as run_analyses
from cartograph.v2.config import RunConfig
from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.base import is_err
from cartograph.v2.pipeline import Pipeline
from cartograph.v2.stages.annotate.registry import default_annotators
from cartograph.v2.stages.discover.topology import TopologyDiscoverer
from cartograph.v2.stages.extract.treesitter_extractor import TreesitterExtractor
from cartograph.v2.stages.present.cli import CliPresenter
from cartograph.v2.stages.present.markdown import codebase_markdown, flow_markdown
from cartograph.v2.stages.present.web_serializers import (
    serialize_callers,
    serialize_graph_trace,
    serialize_search,
)
from cartograph.v2.stages.resolve.lsp.server import LspServer
from cartograph.v2.stages.resolve.ty_resolver import TyResolver

INSTRUCTIONS = """\
Deterministic call-graph context for a Python project.

Every tool returns structured, ground-truth facts derived from static analysis
(tree-sitter extraction + ty LSP resolution). Prefer `context` for LLM
reasoning (markdown facts), `trace`/`callers` for programmatic consumption
(structured JSON). `analyze` surfaces N+1, hotspots, and async-boundary risks.
No narration tool is exposed — the caller handles prose.\
"""


def _resolve_qname(functions: dict[str, Any], name: str) -> str | None:
    """exact → suffix → substring. First hit wins."""
    if name in functions:
        return name
    for qn in functions:
        if qn.endswith(f".{name}"):
            return qn
    needle = name.lower()
    for qn in functions:
        if needle in qn.lower():
            return qn
    return None


def build_server(project_root: Path) -> FastMCP:
    """Construct an MCP server bound to one project. Graph is built on first tool call."""
    project_root = project_root.resolve()
    mcp: FastMCP = FastMCP("cartograph", instructions=INSTRUCTIONS)

    cache: dict[str, AnalyzedGraph] = {}
    lock = asyncio.Lock()

    async def graph() -> AnalyzedGraph:
        async with lock:
            if "g" in cache:
                return cache["g"]
            async with LspServer(["ty", "server"]) as server:
                pipeline = Pipeline(
                    extractor=TreesitterExtractor(),
                    resolver=TyResolver(server=server),
                    annotators=default_annotators(),
                    discoverer=TopologyDiscoverer(),
                    presenter=CliPresenter(),
                )
                result = await pipeline.build(RunConfig(project_root=project_root))
            if is_err(result):
                raise RuntimeError(f"pipeline failed: {result.error}")
            cache["g"] = result.value
            return result.value

    @mcp.tool
    async def scan() -> dict[str, int]:
        """Summary stats: module, function, edge, unresolved, entry-point counts."""
        g = await graph()
        resolved = g.annotated.resolved
        modules = {f.module for f in resolved.functions.values()}
        return {
            "modules": len(modules),
            "functions": len(resolved.functions),
            "edges": len(resolved.edges),
            "unresolved": len(resolved.unresolved),
            "entry_points": len(g.entry_points),
        }

    @mcp.tool
    async def entries(kind: str | None = None) -> list[dict[str, Any]]:
        """Discovered entry points. Filter by kind: api_route, celery_task, signal_handler, discovered."""
        g = await graph()
        return [
            ep.model_dump() for ep in g.entry_points if kind is None or ep.kind == kind
        ]

    @mcp.tool
    async def trace(qname: str, depth: int = 5) -> dict[str, Any]:
        """Call tree rooted at qname. Cytoscape-compatible nodes + edges + metadata.

        `qname` accepts exact qualified name, unique suffix, or substring.
        """
        g = await graph()
        resolved_qname = _resolve_qname(g.annotated.resolved.functions, qname)
        if resolved_qname is None:
            raise ValueError(f"unknown qname: {qname}")
        return serialize_graph_trace(g, resolved_qname, depth)

    @mcp.tool
    async def callers(qname: str) -> dict[str, Any]:
        """Reverse lookup — functions that call qname."""
        g = await graph()
        resolved_qname = _resolve_qname(g.annotated.resolved.functions, qname)
        if resolved_qname is None:
            raise ValueError(f"unknown qname: {qname}")
        return serialize_callers(g, resolved_qname)

    @mcp.tool
    async def search(query: str, limit: int = 20) -> dict[str, Any]:
        """Substring search over qualified names."""
        g = await graph()
        return serialize_search(g, query, limit)

    @mcp.tool
    async def context(qname: str | None = None, depth: int = 5) -> str:
        """Deterministic markdown for LLM reasoning.

        With qname: flow-level (call tree rooted at qname, file:line refs).
        Without: codebase-level (stats + entry points + top callers).
        """
        g = await graph()
        if qname is None:
            return codebase_markdown(g)
        resolved_qname = _resolve_qname(g.annotated.resolved.functions, qname)
        if resolved_qname is None:
            raise ValueError(f"unknown qname: {qname}")
        return flow_markdown(g, resolved_qname, depth)

    @mcp.tool
    async def analyze() -> dict[str, Any]:
        """Engineering-insight analyses: N+1 ORM candidates, model hotspots,
        mixed-operation functions, async-boundary crossings."""
        g = await graph()
        return run_analyses(g).model_dump()

    return mcp


def serve(project_root: Path) -> None:
    """Run the MCP server on stdio until the host disconnects."""
    mcp = build_server(project_root)
    mcp.run(transport="stdio", show_banner=False)
