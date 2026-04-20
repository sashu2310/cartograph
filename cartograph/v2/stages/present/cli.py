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
from cartograph.v2.ir.resolved import ResolvedGraph
from cartograph.v2.stages.present.util import bucket_unresolved

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


def _class_count(resolved: ResolvedGraph) -> int:
    return sum(1 for fn in resolved.functions.values() if fn.kind == "class")


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
