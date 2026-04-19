"""CommonGraph — lossy benchmarking IR, the shared shape all producers export to."""

from __future__ import annotations

from cartograph.v2.ir.base import IR


class CommonFunction(IR):
    qname: str
    module: str
    name: str
    line: int
    decorators: tuple[str, ...] = ()


class CommonEdge(IR):
    caller: str
    callee: str
    line: int


class CommonEntryPoint(IR):
    qname: str
    kind: str  # free-form; adapters normalize to a shared vocabulary
    trigger: str | None = None


class CommonGraph(IR):
    """Minimal shared IR for benchmarking. See module docstring."""

    project_name: str
    project_commit: str | None = None
    producer: str  # "v1" | "v2-ty" | ...
    functions: dict[str, CommonFunction] = {}  # noqa: RUF012 — pydantic deep-copies defaults
    edges: tuple[CommonEdge, ...] = ()
    entry_points: tuple[CommonEntryPoint, ...] = ()

    @property
    def edge_set(self) -> frozenset[tuple[str, str]]:
        """Set of (caller, callee) pairs, order-free, line-agnostic.

        Used by metrics.py for set-difference comparisons between graphs.
        """
        return frozenset((e.caller, e.callee) for e in self.edges)

    @property
    def entry_qnames(self) -> frozenset[str]:
        return frozenset(e.qname for e in self.entry_points)
