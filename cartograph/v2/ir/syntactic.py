"""Stage 1 output — syntactic facts extracted per file. No resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Discriminator

from cartograph.v2.ir.base import IR


class DecoratorSpec(IR):
    """Decorator name plus literal-constant args.

    `line` and `col` locate the decorator's target identifier (the `app.get`
    part of `@app.get("/x")`) so Stage 2 can resolve it via LSP
    `textDocument/definition`, the same way call sites get resolved. Values
    of 0 mean the extractor didn't capture position — the annotator falls
    back to name-based matching in that case.

    Non-constant args are dropped; values are stringified so the IR stays
    JSON-friendly.
    """

    name: str
    args: tuple[str, ...] = ()
    kwargs: dict[str, str] = {}  # noqa: RUF012 — pydantic deep-copies defaults
    line: int = 0
    col: int = 0


class ImportStmt(IR):
    """`from .foo import Bar as B` → module="foo", name="Bar", alias="B", level=1.

    `line` is the 1-based source line where the import statement starts.
    Legacy caches without this field default to 0; consumers that need
    precise locations (rename-impact, import-cycle detection) treat 0 as
    "unknown, fall back to module-level reporting."
    """

    module: str
    name: str | None = None
    alias: str | None = None
    is_relative: bool = False
    level: int = 0
    line: int = 0


class PlainCall(IR):
    kind: Literal["plain"] = "plain"
    name: str
    line: int
    col: int


class MethodCall(IR):
    kind: Literal["method"] = "method"
    name: str
    receiver: str
    receiver_chain: tuple[str, ...]
    line: int
    col: int


class AsyncDispatchCall(IR):
    """`task.delay(...)` or `task.apply_async(...)`."""

    kind: Literal["async_dispatch"] = "async_dispatch"
    name: str
    receiver: str
    receiver_chain: tuple[str, ...]
    dispatch_kind: Literal["delay", "apply_async"]
    line: int
    col: int


class AsyncOrchestrationCall(IR):
    """Celery `chain`, `chord`, `group` — syntactically plain calls, semantically
    dispatch: the callee is the orchestration result, not any one task."""

    kind: Literal["async_orchestration"] = "async_orchestration"
    name: Literal["chain", "chord", "group"]
    line: int
    col: int


CallKind = Annotated[
    PlainCall | MethodCall | AsyncDispatchCall | AsyncOrchestrationCall,
    Discriminator("kind"),
]


class CallSite(IR):
    caller_qname: str
    call: CallKind
    condition: str | None = None


class SyncFunction(IR):
    kind: Literal["sync"] = "sync"
    qname: str
    name: str
    class_name: str | None = None
    decorators: tuple[DecoratorSpec, ...] = ()
    line_start: int
    line_end: int
    docstring: str | None = None
    call_sites: tuple[CallSite, ...] = ()

    @property
    def decorator_names(self) -> tuple[str, ...]:
        return tuple(d.name for d in self.decorators)


class AsyncFunction(IR):
    kind: Literal["async"] = "async"
    qname: str
    name: str
    class_name: str | None = None
    decorators: tuple[DecoratorSpec, ...] = ()
    line_start: int
    line_end: int
    docstring: str | None = None
    call_sites: tuple[CallSite, ...] = ()

    @property
    def decorator_names(self) -> tuple[str, ...]:
        return tuple(d.name for d in self.decorators)


SyntacticFunction = Annotated[
    SyncFunction | AsyncFunction,
    Discriminator("kind"),
]


class SyntacticClass(IR):
    qname: str
    name: str
    bases: tuple[str, ...] = ()
    decorators: tuple[DecoratorSpec, ...] = ()
    line_start: int
    line_end: int

    @property
    def decorator_names(self) -> tuple[str, ...]:
        return tuple(d.name for d in self.decorators)


class SyntacticModule(IR):
    path: Path
    module_name: str
    content_hash: str
    language: Literal["python"] = "python"
    imports: tuple[ImportStmt, ...] = ()
    classes: tuple[SyntacticClass, ...] = ()
    functions: tuple[SyntacticFunction, ...] = ()
