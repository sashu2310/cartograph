"""pydantic-ai Agent that narrates a call flow. Model via options, env, or default."""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
from collections.abc import Coroutine
from typing import Any, Literal

from pydantic_ai import Agent

from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.resolved import Edge, ResolvedGraph

OutputFormat = Literal["cli", "json", "html", "markdown", "mermaid", "dot"]

DEFAULT_MODEL = "anthropic:claude-sonnet-4-5"
SYSTEM_PROMPT = """\
You are a senior engineer explaining Python call flows to a teammate who \
just joined the project. You receive a serialized call tree (caller → callees, \
with file and line references) and produce a concise narrative: what this entry \
point does, which helpers it relies on, and any notable patterns (branching, \
async dispatch, framework hooks). Keep it under 250 words. Use plain prose. \
No bullet lists unless the flow genuinely has parallel branches.\
"""


class LlmPresenter:
    name: str = "llm"
    output_format: OutputFormat = "markdown"

    def render(self, graph: AnalyzedGraph, options: dict[str, Any]) -> bytes:
        """Render narrative text for one entry point.

        Required option: `entry_qname: str` — which function to narrate.
        Optional: `model: str`, `depth: int`.
        """
        entry_qname = options.get("entry_qname")
        if entry_qname is None:
            raise ValueError("LlmPresenter requires options['entry_qname']")
        depth = options.get("depth", 4)
        model = options.get("model") or os.getenv("CARTOGRAPH_LLM_MODEL", DEFAULT_MODEL)

        narrative = _run_sync(
            narrate_flow(graph, entry_qname, depth=depth, model=model)
        )
        return narrative.encode("utf-8")


def _run_sync(coro: Coroutine[Any, Any, str]) -> str:
    """Run an async coroutine from sync code, even if a loop is already live.

    In a fresh interpreter, `asyncio.run` is fine. In Jupyter / IPython / an
    async CLI, a loop is already running and `asyncio.run` would raise. Offload
    to a worker thread so `asyncio.run` gets its own loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def narrate_flow(
    graph: AnalyzedGraph,
    entry_qname: str,
    *,
    depth: int = 4,
    model: str = DEFAULT_MODEL,
) -> str:
    resolved = graph.annotated.resolved
    if entry_qname not in resolved.functions:
        raise ValueError(f"unknown qname: {entry_qname}")

    flow_text = _serialize_flow(resolved, entry_qname, depth=depth)
    agent = _build_agent(model)
    result = await agent.run(flow_text)
    return _extract_output(result)


def _build_agent(model: str) -> Agent:
    return Agent(model, system_prompt=SYSTEM_PROMPT)


def _extract_output(result: Any) -> str:
    """pydantic-ai has shifted its result API across versions. Try the known
    shapes; fall back to `str(result)`."""
    for attr in ("output", "data", "value"):
        if hasattr(result, attr):
            return str(getattr(result, attr))
    return str(result)


def _serialize_flow(resolved: ResolvedGraph, root: str, *, depth: int) -> str:
    """Render the call tree rooted at `root` as indented text with file:line
    references on each node. Depth-limited to keep context compact."""
    root_ref = resolved.functions.get(root)
    lines: list[str] = []
    if root_ref is not None:
        lines.append(f"Entry point: {root_ref.qname}")
        lines.append(
            f"  file: {root_ref.source_path} (lines {root_ref.line_start}-{root_ref.line_end})"
        )
        if root_ref.decorators:
            lines.append(f"  decorators: {', '.join(root_ref.decorators)}")
    lines.append("")
    lines.append("Call tree (indented by depth):")

    seen: set[str] = set()
    _render_tree(resolved, root, depth, indent=0, seen=seen, out=lines)

    return "\n".join(lines)


def _render_tree(
    resolved: ResolvedGraph,
    qname: str,
    depth_left: int,
    *,
    indent: int,
    seen: set[str],
    out: list[str],
) -> None:
    prefix = "  " * indent
    ref = resolved.functions.get(qname)
    label = ref.qname if ref else qname
    if qname in seen:
        out.append(f"{prefix}- {label}  [cycle]")
        return
    out.append(f"{prefix}- {label}")
    if depth_left <= 0:
        return
    seen.add(qname)
    for edge in _stable_edges(resolved.get_callees(qname)):
        cond = f"  [if {edge.condition}]" if edge.condition else ""
        out.append(f"{prefix}  → (line {edge.line}){cond}")
        _render_tree(
            resolved,
            edge.callee_qname,
            depth_left - 1,
            indent=indent + 1,
            seen=seen,
            out=out,
        )
    seen.discard(qname)


def _stable_edges(edges: tuple[Edge, ...]) -> tuple[Edge, ...]:
    return tuple(sorted(edges, key=lambda e: (e.line, e.callee_qname)))
