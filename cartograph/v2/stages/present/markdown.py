"""Deterministic markdown emitters — codebase-level and flow-level.

These are the agent-facing counterpart to `llm.py`. Output is pure structural
fact (no narration); LLMs consume it directly.
"""

from __future__ import annotations

from collections import Counter

from cartograph.v2.ir.analyzed import AnalyzedGraph


def codebase_markdown(graph: AnalyzedGraph) -> str:
    """Codebase-level markdown. No source snippets — LLMs read files themselves."""
    from cartograph.v2.stages.present.util import (
        bucket_unresolved,
        top_classes_by_usage,
    )

    resolved = graph.annotated.resolved
    functions = resolved.functions
    eps_by_kind = Counter(ep.kind for ep in graph.entry_points)
    top_callers = sorted(
        (
            (qn, len(resolved.get_callees(qn)))
            for qn, fn in functions.items()
            if fn.kind != "class"
        ),
        key=lambda x: -x[1],
    )[:15]
    class_count = sum(1 for fn in functions.values() if fn.kind == "class")
    top_classes = top_classes_by_usage(resolved, limit=15)
    buckets = bucket_unresolved(resolved.unresolved)

    lines = [
        "# Codebase Analysis (cartograph v2)\n",
        f"- Functions: {len(functions)}",
        f"- Classes: {class_count}",
        f"- Resolved edges: {len(resolved.edges)}",
        f"- Unresolved: {len(resolved.unresolved)}"
        + (
            " ("
            + ", ".join(
                f"{v} {k}" for k, v in sorted(buckets.items(), key=lambda x: -x[1])
            )
            + ")"
            if buckets
            else ""
        ),
        f"- Entry points: {len(graph.entry_points)}\n",
        "## Entry Points by Kind\n",
    ]
    for kind, count in eps_by_kind.most_common():
        lines.append(f"**{kind}** ({count}):")
        samples = [ep for ep in graph.entry_points if ep.kind == kind][:8]
        for ep in samples:
            lines.append(f"  - {ep.qname}")
        lines.append("")

    if top_classes:
        lines.append("## Top Classes by Usage\n")
        for qn, count in top_classes:
            lines.append(f"  {count:>3}  {qn}")
        lines.append("")

    lines.append("## Top Functions by Outgoing Calls\n")
    for qn, count in top_callers:
        lines.append(f"  {count:>3}  {qn}")

    return "\n".join(lines)


def flow_markdown(
    graph: AnalyzedGraph,
    root_qname: str,
    depth: int,
    *,
    max_tokens: int | None = None,
) -> str:
    """Flow-level markdown. Call tree as a flat indented list.

    If `max_tokens` is given, the walk stops greedy-BFS-style once the
    accumulated output exceeds that budget. Tokens approximated as
    `len(output) / 4` — the standard rule-of-thumb for English-like
    text, accurate to ~10% for most LLM tokenizers.
    """
    resolved = graph.annotated.resolved
    root = resolved.functions[root_qname]
    lines = [
        f"# Flow Analysis: {root_qname} (cartograph v2)\n",
        f"- Location: {root.source_path}:{root.line_start}",
    ]
    if root.decorators:
        lines.append(f"- Decorators: {', '.join(root.decorators)}")
    lines.append("")
    lines.append("## Call Tree\n")

    seen: set[str] = set()
    truncated = False

    def over_budget() -> bool:
        if max_tokens is None:
            return False
        # chars/4 is the standard tokens-approximation heuristic.
        return sum(len(line) for line in lines) >= max_tokens * 4

    def walk(qname: str, d: int, indent: int) -> bool:
        """Returns True if the walk should abort (budget exceeded)."""
        nonlocal truncated
        prefix = "  " * indent
        if qname in seen:
            lines.append(f"{prefix}- {qname}  (cycle)")
            return False
        lines.append(f"{prefix}- {qname}")
        if over_budget():
            truncated = True
            return True
        if d <= 0:
            return False
        seen.add(qname)
        for edge in resolved.get_callees(qname):
            cond = f"  [if {edge.condition}]" if edge.condition else ""
            lines.append(f"{prefix}  line {edge.line}{cond}")
            if over_budget():
                truncated = True
                return True
            if walk(edge.callee_qname, d - 1, indent + 1):
                return True
        seen.discard(qname)
        return False

    walk(root_qname, depth, 0)
    if truncated and max_tokens is not None:
        lines.append("")
        lines.append(f"_(truncated at ~{max_tokens} tokens)_")
    return "\n".join(lines)


def callers_markdown(graph: AnalyzedGraph, target_qname: str) -> str:
    """Question-scoped: who calls this function? Fewer tokens than a flow tree."""
    resolved = graph.annotated.resolved
    target = resolved.functions[target_qname]
    lines = [
        f"# Callers of {target_qname}\n",
        f"- Defined at: {target.source_path}:{target.line_start}",
        "",
    ]
    edges = resolved.get_callers(target_qname)
    if not edges:
        lines.append("_No callers found in the project graph._")
        lines.append("")
        lines.append(
            "Possible reasons: entry point (called by a framework), "
            "exported for external use, or reached only via dynamic dispatch."
        )
        return "\n".join(lines)

    lines.append(f"## Direct callers ({len(edges)})\n")
    for edge in sorted(edges, key=lambda e: (e.caller_qname, e.line)):
        caller = resolved.functions.get(edge.caller_qname)
        loc = f"{caller.source_path.name}:{edge.line}" if caller else f"?:{edge.line}"
        async_tag = f" [{edge.async_kind}]" if edge.async_kind else ""
        lines.append(f"- `{edge.caller_qname}` at {loc}{async_tag}")
    return "\n".join(lines)


def callees_markdown(graph: AnalyzedGraph, target_qname: str) -> str:
    """Question-scoped: what does this function call? One-hop only."""
    resolved = graph.annotated.resolved
    target = resolved.functions[target_qname]
    lines = [
        f"# Callees of {target_qname}\n",
        f"- Defined at: {target.source_path}:{target.line_start}",
        "",
    ]
    edges = resolved.get_callees(target_qname)
    if not edges:
        lines.append("_This function makes no calls to other project functions._")
        return "\n".join(lines)

    lines.append(f"## Direct callees ({len(edges)})\n")
    for edge in sorted(edges, key=lambda e: (e.line, e.callee_qname)):
        callee = resolved.functions.get(edge.callee_qname)
        loc = (
            f"{callee.source_path.name}:{callee.line_start}" if callee else "<external>"
        )
        async_tag = f" [{edge.async_kind}]" if edge.async_kind else ""
        cond = f" if {edge.condition}" if edge.condition else ""
        lines.append(
            f"- line {edge.line}: `{edge.callee_qname}` → {loc}{async_tag}{cond}"
        )
        if edge.callee_signature:
            lines.append(f"    - signature: `{edge.callee_signature}`")
    return "\n".join(lines)


def parse_answer_question(query: str) -> tuple[str, str] | None:
    """Parse a natural-language `--answer` query into (kind, target).

    Recognised shapes (case-insensitive):
        "what calls X"        → ("callers", "X")
        "callers of X"        → ("callers", "X")
        "who calls X"         → ("callers", "X")
        "what does X call"    → ("callees", "X")
        "calls from X"        → ("callees", "X")
        "flow of X"           → ("flow", "X")

    Returns None if the query doesn't match a known shape.
    """
    import re

    q = query.strip()
    patterns = [
        (r"^(?:what calls|callers of|who calls)\s+(\S+)\s*$", "callers"),
        (
            r"^(?:what does\s+(\S+)\s+call|calls from\s+(\S+))\s*$",
            "callees",
        ),
        (r"^(?:flow of|trace of)\s+(\S+)\s*$", "flow"),
    ]
    for pattern, kind in patterns:
        match = re.match(pattern, q, flags=re.IGNORECASE)
        if match:
            target = next(g for g in match.groups() if g)
            return (kind, target)
    return None
