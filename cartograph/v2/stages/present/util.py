"""Shared graph-query helpers consumed by multiple presenters.

These live here because the CLI presenter, markdown presenter, web
serializers, MCP server, and the rich-CLI render layer all need them.
They produce plain Python values (dicts, tuples of tuples) — no
presentation decisions — so every surface can format the result
however it wants.
"""

from __future__ import annotations

from collections import defaultdict

from cartograph.v2.ir.resolved import ResolvedGraph, UnresolvedCall


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
