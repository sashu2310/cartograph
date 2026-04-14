"""Flow narrator — combines graph data + source code + LLM to narrate flows."""

from pathlib import Path

from cartograph.graph.call_graph import CallGraph
from cartograph.llm.prompts import NARRATE_SYSTEM, build_narration_prompt
from cartograph.llm.provider import LLMProvider, LLMResponse
from cartograph.web.serializers import serialize_graph_trace


def narrate_flow(
    graph: CallGraph,
    qname: str,
    provider: LLMProvider,
    depth: int = 5,
    max_source_nodes: int = 5,
) -> LLMResponse:
    """Narrate a code flow from an entry point.

    1. Serialize the subgraph to JSON
    2. Read source code for key nodes
    3. Send graph + source to the LLM
    4. Return the narrative
    """
    graph_json = serialize_graph_trace(graph, qname, depth)

    # Read source snippets for the most connected nodes
    snippets = _read_source_snippets(graph, graph_json, max_source_nodes)

    user_prompt = build_narration_prompt(graph_json, snippets)

    return provider.narrate(system=NARRATE_SYSTEM, user=user_prompt)


def _read_source_snippets(
    graph: CallGraph,
    graph_json: dict,
    max_nodes: int,
) -> dict[str, str]:
    """Read source code for key nodes in the graph."""
    snippets: dict[str, str] = {}

    # Rank nodes by edge count (most connected first)
    nodes = graph_json.get("nodes", {})
    edges = graph_json.get("edges", [])
    edge_counts: dict[str, int] = {}
    for e in edges:
        edge_counts[e["source"]] = edge_counts.get(e["source"], 0) + 1
        edge_counts[e["target"]] = edge_counts.get(e["target"], 0) + 1

    # Always include the entry point first
    entry = graph_json.get("entry_point", "")
    ranked = [
        entry,
        *sorted(
            [qn for qn in nodes if qn != entry],
            key=lambda qn: edge_counts.get(qn, 0),
            reverse=True,
        ),
    ]

    for qname in ranked[:max_nodes]:
        node = nodes.get(qname, {})
        file_path = node.get("file", "")
        line_start = node.get("line_start", 0)
        line_end = node.get("line_end", 0)

        if not file_path or not line_start:
            continue

        snippet = _read_lines(file_path, line_start, line_end)
        if snippet:
            snippets[qname] = snippet

    return snippets


def _read_lines(file_path: str, start: int, end: int) -> str | None:
    """Read specific lines from a file."""
    path = Path(file_path)
    if not path.exists():
        return None

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        # Clamp to file bounds, limit to 60 lines max
        start_idx = max(0, start - 1)
        end_idx = min(len(lines), end)
        if end_idx - start_idx > 60:
            end_idx = start_idx + 60
        return "\n".join(lines[start_idx:end_idx])
    except (OSError, UnicodeDecodeError):
        return None
