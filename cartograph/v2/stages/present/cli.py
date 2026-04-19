"""Plain-text terminal summary. No color; deterministic output for diffs."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal

from cartograph.v2.ir.analyzed import (
    AnalyzedGraph,
    ApiRouteEntry,
    CeleryTaskEntry,
    DiscoveredEntry,
    EntryPoint,
    SignalHandlerEntry,
)
from cartograph.v2.ir.resolved import ResolvedGraph, UnresolvedCall

OutputFormat = Literal["cli", "json", "html", "markdown", "mermaid", "dot"]


class CliPresenter:
    name: str = "cli"
    output_format: OutputFormat = "cli"

    def render(self, graph: AnalyzedGraph, options: dict[str, Any]) -> bytes:
        resolved = graph.annotated.resolved
        lines: list[str] = []

        lines.append("CARTOGRAPH v2 — scan summary")
        lines.append("─" * 40)
        lines.append(f"  functions      {len(resolved.functions)}")
        lines.append(f"  classes        {_class_count(resolved)}")
        lines.append(f"  edges          {len(resolved.edges)}")
        lines.append(f"  unresolved     {len(resolved.unresolved)}")
        for reason, count in sorted(
            bucket_unresolved(resolved.unresolved).items(),
            key=lambda x: (-x[1], x[0]),
        ):
            lines.append(f"    {reason:<12} {count}")
        lines.append(f"  entry points   {len(graph.entry_points)}")
        lines.append("")

        if graph.entry_points:
            by_kind = _group_by_kind(graph.entry_points)
            for kind in sorted(by_kind):
                entries = by_kind[kind]
                lines.append(f"{kind} ({len(entries)})")
                for ep in entries:
                    lines.append(f"  {_format_entry(ep)}")
                lines.append("")

        return "\n".join(lines).encode("utf-8")


def bucket_unresolved(unresolved: tuple[UnresolvedCall, ...]) -> dict[str, int]:
    """Group unresolved calls into four readable buckets.

    The IR distinguishes six reasons (builtin / external / lsp_empty /
    lsp_timeout / lsp_error / unknown); we collapse the three LSP reasons
    into one bucket because the distinction rarely matters to a human
    reader. Use the full `.reason` field on UnresolvedCall when it does.
    """
    counts: dict[str, int] = defaultdict(int)
    for u in unresolved:
        reason = u.reason
        if reason.startswith("lsp_"):
            counts["lsp"] += 1
        else:
            counts[reason] += 1
    return dict(counts)


def _class_count(resolved: ResolvedGraph) -> int:
    return sum(1 for fn in resolved.functions.values() if fn.kind == "class")


def top_classes_by_usage(
    resolved: ResolvedGraph, limit: int = 10
) -> list[tuple[str, int]]:
    """Top-N classes by incoming-edge count (how often they're constructed
    or referenced). Returns [(qname, count), ...] sorted desc."""
    scored = [
        (qn, len(resolved.callers_by_callee.get(qn, ())))
        for qn, fn in resolved.functions.items()
        if fn.kind == "class"
    ]
    scored.sort(key=lambda x: (-x[1], x[0]))
    return [row for row in scored if row[1] > 0][:limit]


def ranked_search(
    resolved: ResolvedGraph, query: str, limit: int = 20
) -> list[tuple[int, str]]:
    """Score each qname against a case-insensitive query, return sorted matches.

    Ranking (highest first):
        100  function name equals query exactly
         50  function name starts with query
         25  query appears anywhere in function name
         10  query appears only in module path (not in function name)
          0  no match — excluded

    Ties broken by qname ascending for deterministic output. Returns
    `[(score, qname), ...]`.
    """
    needle = query.lower()
    scored: list[tuple[int, str]] = []
    for qname in resolved.functions:
        name = qname.rsplit(".", 1)[-1].lower()
        if name == needle:
            score = 100
        elif name.startswith(needle):
            score = 50
        elif needle in name:
            score = 25
        elif needle in qname.lower():
            score = 10
        else:
            continue
        scored.append((score, qname))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return scored[:limit]


def _group_by_kind(
    entries: tuple[EntryPoint, ...],
) -> dict[str, list[EntryPoint]]:
    out: dict[str, list[EntryPoint]] = defaultdict(list)
    for ep in entries:
        out[ep.kind].append(ep)
    # Sort each bucket by qname for deterministic output.
    for bucket in out.values():
        bucket.sort(key=lambda e: e.qname)
    return dict(out)


def _format_entry(ep: EntryPoint) -> str:
    if isinstance(ep, ApiRouteEntry):
        return f"{ep.method:<6} {ep.path:<30} → {ep.qname}"
    if isinstance(ep, CeleryTaskEntry):
        queue = f"[{ep.queue}]" if ep.queue else ""
        return f"{ep.qname} {queue}".strip()
    if isinstance(ep, SignalHandlerEntry):
        sender = f" from {ep.sender}" if ep.sender else ""
        return f"{ep.qname}  signal={ep.signal_name}{sender}"
    if isinstance(ep, DiscoveredEntry):
        return f"{ep.qname}  @{ep.trigger_decorator}"
    return f"{ep.qname}"
