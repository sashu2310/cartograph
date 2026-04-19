"""Pairwise overlap metrics between two CommonGraphs. No accuracy claims — no external ground truth."""

from __future__ import annotations

from typing import Literal

from cartograph.v2.ir.base import IR
from cartograph.v2.ir.common import CommonGraph

Target = Literal["v1", "v2-ty"]


class BenchmarkResult(IR):
    """One producer's run output plus metadata. `graph` is the CommonGraph the
    producer produced; `wall_time_s` / `peak_memory_mb` measure the run itself."""

    target: Target
    project_name: str
    project_commit: str | None = None
    version: str
    total_call_sites: int
    resolved_count: int
    unresolved_count: int
    wall_time_s: float
    peak_memory_mb: float
    graph: CommonGraph


class ComparisonReport(IR):
    """Pairwise structural overlap between two producers' graphs.

    Fields:
      shared_edges         — (caller, callee) pairs both producers found.
      only_a               — edges only producer A found.
      only_b               — edges only producer B found.
      shared_entry_points  — entry-point qnames both found.
      jaccard              — |shared| / |shared U only_a U only_b|.
                             Symmetric, order-free overlap measure.
      a_corroborated_by_b  — fraction of A's edges that B also found.
      b_corroborated_by_a  — fraction of B's edges that A also found.

    These are descriptive statistics. They say nothing about correctness.
    """

    a: BenchmarkResult
    b: BenchmarkResult
    shared_edges: int
    only_a: int
    only_b: int
    shared_entry_points: int
    jaccard: float
    a_corroborated_by_b: float
    b_corroborated_by_a: float


def compare(a: BenchmarkResult, b: BenchmarkResult) -> ComparisonReport:
    """Compute pairwise overlap between two producers. Order-insensitive for
    structural fields; labels A and B preserve the argument order for the
    asymmetric corroboration rates."""
    edges_a = a.graph.edge_set
    edges_b = b.graph.edge_set

    shared = edges_a & edges_b
    just_a = edges_a - edges_b
    just_b = edges_b - edges_a

    union_size = len(shared) + len(just_a) + len(just_b)
    jaccard = len(shared) / union_size if union_size else 0.0

    a_corroborated = len(shared) / len(edges_a) if edges_a else 0.0
    b_corroborated = len(shared) / len(edges_b) if edges_b else 0.0

    shared_eps = len(a.graph.entry_qnames & b.graph.entry_qnames)

    return ComparisonReport(
        a=a,
        b=b,
        shared_edges=len(shared),
        only_a=len(just_a),
        only_b=len(just_b),
        shared_entry_points=shared_eps,
        jaccard=jaccard,
        a_corroborated_by_b=a_corroborated,
        b_corroborated_by_a=b_corroborated,
    )


def format_report(report: ComparisonReport) -> str:
    """Pretty-printable pairwise overlap summary."""
    a = report.a
    b = report.b
    lines = [
        f"{'':<22}  {a.target:<12}  {b.target:<12}",
        "─" * 56,
        f"{'project':<22}  {a.project_name}",
        f"{'commit':<22}  {a.project_commit or '(none)'}",
        "",
        f"{'functions':<22}  {len(a.graph.functions):<12}  {len(b.graph.functions):<12}",
        f"{'edges':<22}  {len(a.graph.edges):<12}  {len(b.graph.edges):<12}",
        f"{'entry points':<22}  {len(a.graph.entry_points):<12}  {len(b.graph.entry_points):<12}",
        f"{'wall time (s)':<22}  {a.wall_time_s:<12.2f}  {b.wall_time_s:<12.2f}",
        f"{'peak memory (MB)':<22}  {a.peak_memory_mb:<12.1f}  {b.peak_memory_mb:<12.1f}",
        "",
        "Edge overlap:",
        f"  shared                         {report.shared_edges}",
        f"  only {a.target:<18}        {report.only_a}",
        f"  only {b.target:<18}        {report.only_b}",
        f"  shared entry points            {report.shared_entry_points}",
        "",
        f"  jaccard                        {report.jaccard:.3f}",
        f"  {a.target} corroborated by {b.target}   {report.a_corroborated_by_b:.3f}",
        f"  {b.target} corroborated by {a.target}   {report.b_corroborated_by_a:.3f}",
    ]
    return "\n".join(lines)
