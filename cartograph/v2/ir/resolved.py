"""Stage 2 output — a connected graph. Unresolved calls carry typed reasons."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Discriminator, model_validator

from cartograph.v2.ir.base import IR


class FunctionRef(IR):
    qname: str
    name: str
    module: str
    class_name: str | None = None
    decorators: tuple[str, ...] = ()
    line_start: int
    line_end: int
    source_path: Path
    kind: Literal["function", "method", "class"] = "function"
    docstring: str | None = None


AsyncKind = Literal[
    "celery_delay",
    "celery_apply_async",
    "celery_chain",
    "celery_chord",
    "celery_group",
]


class Edge(IR):
    caller_qname: str
    callee_qname: str
    line: int
    condition: str | None = None
    async_kind: AsyncKind | None = None  # None => sync call


class BuiltinUnresolved(IR):
    reason: Literal["builtin"] = "builtin"
    caller_qname: str
    name: str
    line: int


class ExternalUnresolved(IR):
    reason: Literal["external"] = "external"
    caller_qname: str
    name: str
    line: int
    target_module: str | None = None


class LspUnresolved(IR):
    reason: Literal["lsp_empty", "lsp_timeout", "lsp_error"]
    caller_qname: str
    name: str
    line: int
    error_detail: str | None = None


class UnknownUnresolved(IR):
    reason: Literal["unknown"] = "unknown"
    caller_qname: str
    name: str
    line: int


UnresolvedCall = Annotated[
    BuiltinUnresolved | ExternalUnresolved | LspUnresolved | UnknownUnresolved,
    Discriminator("reason"),
]


class ResolvedGraph(IR):
    functions: dict[str, FunctionRef]
    edges: tuple[Edge, ...] = ()
    unresolved: tuple[UnresolvedCall, ...] = ()

    callees_by_caller: dict[str, tuple[int, ...]] = {}  # noqa: RUF012
    callers_by_callee: dict[str, tuple[int, ...]] = {}  # noqa: RUF012

    @model_validator(mode="after")
    def _build_indexes(self) -> ResolvedGraph:
        if self.callees_by_caller or self.callers_by_callee:
            return self

        callees: dict[str, list[int]] = {}
        callers: dict[str, list[int]] = {}
        for idx, edge in enumerate(self.edges):
            callees.setdefault(edge.caller_qname, []).append(idx)
            callers.setdefault(edge.callee_qname, []).append(idx)

        object.__setattr__(
            self,
            "callees_by_caller",
            {k: tuple(v) for k, v in callees.items()},
        )
        object.__setattr__(
            self,
            "callers_by_callee",
            {k: tuple(v) for k, v in callers.items()},
        )
        return self

    def get_callees(self, qname: str) -> tuple[Edge, ...]:
        idxs = self.callees_by_caller.get(qname, ())
        return tuple(self.edges[i] for i in idxs)

    def get_callers(self, qname: str) -> tuple[Edge, ...]:
        idxs = self.callers_by_callee.get(qname, ())
        return tuple(self.edges[i] for i in idxs)
