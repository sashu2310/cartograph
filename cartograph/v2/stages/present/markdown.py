"""Deterministic markdown emitters — codebase-level and flow-level.

These are the agent-facing counterpart to `llm.py`. Output is pure structural
fact (no narration); LLMs consume it directly.
"""

from __future__ import annotations

from collections import Counter

from cartograph.v2.ir.analyzed import AnalyzedGraph


def codebase_markdown(graph: AnalyzedGraph) -> str:
    """Codebase-level markdown. No source snippets — LLMs read files themselves."""
    from cartograph.v2.stages.present.cli import (
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


def flow_markdown(graph: AnalyzedGraph, root_qname: str, depth: int) -> str:
    """Flow-level markdown. Call tree as a flat indented list."""
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

    def walk(qname: str, d: int, indent: int) -> None:
        prefix = "  " * indent
        if qname in seen:
            lines.append(f"{prefix}- {qname}  (cycle)")
            return
        lines.append(f"{prefix}- {qname}")
        if d <= 0:
            return
        seen.add(qname)
        for edge in resolved.get_callees(qname):
            cond = f"  [if {edge.condition}]" if edge.condition else ""
            lines.append(f"{prefix}  line {edge.line}{cond}")
            walk(edge.callee_qname, d - 1, indent + 1)
        seen.discard(qname)

    walk(root_qname, depth, 0)
    return "\n".join(lines)
