"""TyResolver + the LSP-generic resolve loop. LSP positions are 0-based; IR is 1-based."""

from __future__ import annotations

import asyncio
import bisect
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import unquote, urlparse

import logfire

from cartograph.v2.ir.base import Err_, Ok
from cartograph.v2.ir.errors import (
    LspCrashedError,
    ResolverError,
    ServerUnreachableError,
)
from cartograph.v2.ir.resolved import (
    AsyncKind,
    BuiltinUnresolved,
    Edge,
    ExternalUnresolved,
    FunctionRef,
    LspUnresolved,
    ResolvedDecorator,
    ResolvedGraph,
    UnknownUnresolved,
    UnresolvedCall,
)
from cartograph.v2.ir.syntactic import (
    AsyncDispatchCall,
    AsyncOrchestrationCall,
    CallKind,
    CallSite,
    DecoratorSpec,
    MethodCall,
    PlainCall,
    SyntacticModule,
)
from cartograph.v2.stages.resolve.lsp.client import (
    LspClosedError,
    LspError,
    LspTimeoutError,
)
from cartograph.v2.stages.resolve.lsp.server import LspServer

_BUILTIN_NAMES = frozenset(
    {
        "print",
        "len",
        "range",
        "str",
        "int",
        "float",
        "list",
        "dict",
        "set",
        "tuple",
        "isinstance",
        "type",
        "super",
        "next",
        "iter",
        "enumerate",
        "zip",
        "map",
        "filter",
        "sorted",
        "reversed",
        "hasattr",
        "getattr",
        "setattr",
        "max",
        "min",
        "sum",
        "abs",
        "any",
        "all",
        "open",
        "format",
        "bool",
        "bytes",
        "bytearray",
        "callable",
        "repr",
        "id",
        "hash",
    }
)


class TyResolver:
    name: str = "ty"
    version: str = "0.0.31"

    def __init__(self, server: LspServer) -> None:
        self._server = server

    async def resolve(
        self,
        modules: tuple[SyntacticModule, ...],
        project_root: Path,
    ) -> Ok[ResolvedGraph] | Err_[ResolverError]:
        return await _resolve_via_lsp(
            server=self._server,
            modules=modules,
            project_root=project_root,
            resolver_name=self.name,
        )


async def _resolve_via_lsp(
    *,
    server: LspServer,
    modules: tuple[SyntacticModule, ...],
    project_root: Path,
    resolver_name: str,
) -> Ok[ResolvedGraph] | Err_[ResolverError]:
    """Works with any server that speaks textDocument/definition."""
    with logfire.span(
        f"{resolver_name}-resolve",
        module_count=len(modules),
        root=str(project_root),
    ):
        try:
            await _ensure_initialized(server, project_root)
            await _open_all(server, modules)
        except (LspTimeoutError, LspError, LspClosedError) as exc:
            return Err_(
                error=ServerUnreachableError(detail=f"{type(exc).__name__}: {exc}")
            )
        except Exception as exc:
            return Err_(error=LspCrashedError(detail=str(exc)))

        function_index = _build_function_index(modules)
        functions = _build_function_refs(modules)

        edges, unresolved = await _resolve_all_calls(server, modules, function_index)
        decorators_by_target = await _resolve_all_decorators(
            server, modules, function_index
        )

        return Ok(
            value=ResolvedGraph(
                functions=functions,
                edges=tuple(edges),
                unresolved=tuple(unresolved),
                decorators_by_target=decorators_by_target,
            )
        )


async def _ensure_initialized(server: LspServer, project_root: Path) -> None:
    if not server.is_started:
        await server.start()
    await server.initialize(root_uri=_path_to_uri(project_root))


async def _open_all(server: LspServer, modules: Iterable[SyntacticModule]) -> None:
    for module in modules:
        uri = _path_to_uri(module.path)
        if uri in server.opened_uris:
            continue
        try:
            text = module.path.read_text(encoding="utf-8")
        except OSError:
            continue
        await server.did_open(uri, text)


async def _resolve_all_decorators(
    server: LspServer,
    modules: tuple[SyntacticModule, ...],
    function_index: dict[str, list[tuple[int, int, str]]],
) -> dict[str, tuple[ResolvedDecorator, ...]]:
    """Resolve every decorator's target via LSP, keyed by the function or
    class the decorator is applied to.

    A decorator with `line == 0` is skipped (position unknown — Stage 1
    didn't capture it, or the IR is from a pre-v2.2 cache). Resolution
    failures land as `ResolvedDecorator(resolved_target=None, ...)` so the
    annotators see the decorator existed but couldn't be typed.
    """
    tasks: list[asyncio.Task[tuple[str, ResolvedDecorator]]] = []
    for module in modules:
        module_uri = _path_to_uri(module.path)
        for func in module.functions:
            for dec in func.decorators:
                if dec.line > 0:
                    tasks.append(
                        asyncio.create_task(
                            _resolve_one_decorator(
                                server,
                                func.qname,
                                dec,
                                module_uri,
                                function_index,
                            )
                        )
                    )
        for cls in module.classes:
            for dec in cls.decorators:
                if dec.line > 0:
                    tasks.append(
                        asyncio.create_task(
                            _resolve_one_decorator(
                                server,
                                cls.qname,
                                dec,
                                module_uri,
                                function_index,
                            )
                        )
                    )

    if not tasks:
        return {}

    results = await asyncio.gather(*tasks)
    by_target: dict[str, list[ResolvedDecorator]] = {}
    for target_qname, resolved_dec in results:
        by_target.setdefault(target_qname, []).append(resolved_dec)
    return {k: tuple(v) for k, v in by_target.items()}


async def _resolve_one_decorator(
    server: LspServer,
    applied_to_qname: str,
    dec: DecoratorSpec,
    module_uri: str,
    function_index: dict[str, list[tuple[int, int, str]]],
) -> tuple[str, ResolvedDecorator]:
    """Resolve one decorator; return (applied_to_qname, ResolvedDecorator)."""
    lsp_line = dec.line - 1  # IR is 1-based; LSP is 0-based.
    try:
        locations = await server.definition(
            module_uri, line=lsp_line, character=dec.col
        )
    except (LspTimeoutError, LspError):
        return applied_to_qname, ResolvedDecorator(
            name=dec.name,
            resolved_target=None,
            args=dec.args,
            kwargs=dec.kwargs,
            line=dec.line,
        )

    resolved_target: str | None = None
    if locations:
        loc = locations[0]
        target_uri = loc.get("uri") or loc.get("targetUri")
        target_range = (
            loc.get("range")
            or loc.get("targetSelectionRange")
            or loc.get("targetRange")
        )
        if target_uri and target_range:
            target_path = _uri_to_path_str(target_uri)
            target_line_1 = target_range.get("start", {}).get("line", 0) + 1
            # Project-internal: look up the qname.
            internal = _find_function_at(function_index, target_path, target_line_1)
            if internal is not None:
                resolved_target = internal
            else:
                # External: best-effort site-packages hint.
                resolved_target = _target_module_hint(target_uri)

    return applied_to_qname, ResolvedDecorator(
        name=dec.name,
        resolved_target=resolved_target,
        args=dec.args,
        kwargs=dec.kwargs,
        line=dec.line,
    )


async def _resolve_all_calls(
    server: LspServer,
    modules: tuple[SyntacticModule, ...],
    function_index: dict[str, list[tuple[int, int, str]]],
) -> tuple[list[Edge], list[UnresolvedCall]]:
    tasks: list[asyncio.Task[Edge | UnresolvedCall]] = []
    for module in modules:
        module_uri = _path_to_uri(module.path)
        for func in module.functions:
            for call_site in func.call_sites:
                tasks.append(
                    asyncio.create_task(
                        _resolve_one(server, call_site, module_uri, function_index)
                    )
                )

    results = await asyncio.gather(*tasks)
    edges: list[Edge] = []
    unresolved: list[UnresolvedCall] = []
    for r in results:
        if isinstance(r, Edge):
            edges.append(r)
        else:
            unresolved.append(r)
    return edges, unresolved


async def _resolve_one(
    server: LspServer,
    call_site: CallSite,
    module_uri: str,
    function_index: dict[str, list[tuple[int, int, str]]],
) -> Edge | UnresolvedCall:
    lsp_line, lsp_char = _lsp_position_for(call_site)
    call = call_site.call

    # Builtin fast path — don't bother the server for print/len/…
    if isinstance(call, PlainCall) and call.name in _BUILTIN_NAMES:
        return BuiltinUnresolved(
            caller_qname=call_site.caller_qname,
            name=call.name,
            line=call.line,
        )

    try:
        locations = await server.definition(
            module_uri, line=lsp_line, character=lsp_char
        )
    except LspTimeoutError:
        return LspUnresolved(
            reason="lsp_timeout",
            caller_qname=call_site.caller_qname,
            name=call.name,
            line=call.line,
        )
    except LspError as exc:
        return LspUnresolved(
            reason="lsp_error",
            caller_qname=call_site.caller_qname,
            name=call.name,
            line=call.line,
            error_detail=exc.message,
        )

    if not locations:
        return LspUnresolved(
            reason="lsp_empty",
            caller_qname=call_site.caller_qname,
            name=call.name,
            line=call.line,
        )

    # Normalize to (uri, line) of the definition target.
    loc = locations[0]
    target_uri = loc.get("uri") or loc.get("targetUri")
    target_range = (
        loc.get("range") or loc.get("targetSelectionRange") or loc.get("targetRange")
    )
    if not target_uri or not target_range:
        return UnknownUnresolved(
            caller_qname=call_site.caller_qname,
            name=call.name,
            line=call.line,
        )

    target_path = _uri_to_path_str(target_uri)
    target_line_0 = target_range.get("start", {}).get("line", 0)
    target_line_1 = target_line_0 + 1  # back to 1-based

    callee_qname = _find_function_at(function_index, target_path, target_line_1)
    if callee_qname is None:
        # Target is outside the project (stdlib, third-party, …)
        return ExternalUnresolved(
            caller_qname=call_site.caller_qname,
            name=call.name,
            line=call.line,
            target_module=_target_module_hint(target_uri),
        )

    return Edge(
        caller_qname=call_site.caller_qname,
        callee_qname=callee_qname,
        line=call.line,
        condition=call_site.condition,
        async_kind=_async_kind_from_call(call),
    )


_ORCHESTRATION_TO_KIND: dict[str, AsyncKind] = {
    "chain": "celery_chain",
    "chord": "celery_chord",
    "group": "celery_group",
}


def _async_kind_from_call(call: CallKind) -> AsyncKind | None:
    """Map a syntactic call variant to the Edge.async_kind tag (or None for sync)."""
    if isinstance(call, AsyncDispatchCall):
        return "celery_delay" if call.dispatch_kind == "delay" else "celery_apply_async"
    if isinstance(call, AsyncOrchestrationCall):
        return _ORCHESTRATION_TO_KIND[call.name]
    return None


def _path_to_uri(p: Path) -> str:
    return p.resolve().as_uri()


def _uri_to_path_str(uri: str) -> str:
    """Convert `file:///…` → absolute path string."""
    parsed = urlparse(uri)
    return unquote(parsed.path) if parsed.scheme == "file" else uri


def _target_module_hint(uri: str) -> str | None:
    """Best-effort hint for where an external target lives (informational)."""
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    parts = unquote(parsed.path).split("/")
    if "site-packages" in parts:
        i = parts.index("site-packages")
        if i + 1 < len(parts):
            return parts[i + 1]
    return None


def _lsp_position_for(call_site: CallSite) -> tuple[int, int]:
    """Return (line, char) in LSP's 0-based convention, positioned at the
    identifier we want ty to resolve."""
    call = call_site.call
    # IR lines are 1-based; LSP is 0-based.
    line = call.line - 1

    if isinstance(call, PlainCall):
        return (line, call.col)

    if isinstance(call, MethodCall):
        # Position at the method name: after `receiver_chain[:-1]` and the dot.
        prefix = ".".join(call.receiver_chain[:-1])
        # `len(prefix) + 1` accounts for the trailing dot before the method.
        return (line, call.col + len(prefix) + 1)

    if isinstance(call, AsyncDispatchCall):
        # Want to resolve the receiver (the task), not the dispatch method.
        return (line, call.col)

    # Defensive: unknown CallKind — query at the start of the call.
    return (line, call.col)  # type: ignore[attr-defined]


def _build_function_index(
    modules: Iterable[SyntacticModule],
) -> dict[str, list[tuple[int, int, str]]]:
    """Map path → sorted [(line_start, line_end, qname), …] for functions + classes.
    Constructor calls `Foo()` resolve to the class node; inner-most span wins."""
    index: dict[str, list[tuple[int, int, str]]] = {}
    for module in modules:
        path_str = str(module.path.resolve())
        bucket = index.setdefault(path_str, [])
        for func in module.functions:
            bucket.append((func.line_start, func.line_end, func.qname))
        for cls in module.classes:
            bucket.append((cls.line_start, cls.line_end, cls.qname))
    for bucket in index.values():
        bucket.sort(key=lambda t: t[0])
    return index


def _find_function_at(
    index: dict[str, list[tuple[int, int, str]]],
    path: str,
    line: int,
) -> str | None:
    """Find the function whose span contains `line`; inner-most match wins."""
    bucket = index.get(path)
    if not bucket:
        # Try via resolved path (handles symlinks, relative vs absolute).
        try:
            resolved = str(Path(path).resolve())
        except OSError:
            return None
        bucket = index.get(resolved)
        if not bucket:
            return None

    # Binary search for rightmost candidate whose line_start ≤ line.
    starts = [t[0] for t in bucket]
    i = bisect.bisect_right(starts, line) - 1
    best: str | None = None
    best_size = float("inf")
    while i >= 0:
        start, end, qname = bucket[i]
        if start <= line <= end:
            size = end - start
            if size < best_size:
                best = qname
                best_size = size
        elif end < line:
            break
        i -= 1
    return best


def _build_function_refs(
    modules: Iterable[SyntacticModule],
) -> dict[str, FunctionRef]:
    refs: dict[str, FunctionRef] = {}
    for module in modules:
        for func in module.functions:
            kind = "method" if func.class_name else "function"
            refs[func.qname] = FunctionRef(
                qname=func.qname,
                name=func.name,
                module=module.module_name,
                class_name=func.class_name,
                decorators=tuple(d.name for d in func.decorators),
                line_start=func.line_start,
                line_end=func.line_end,
                source_path=module.path,
                kind=kind,
            )
        for cls in module.classes:
            refs[cls.qname] = FunctionRef(
                qname=cls.qname,
                name=cls.name,
                module=module.module_name,
                class_name=None,
                decorators=tuple(d.name for d in cls.decorators),
                line_start=cls.line_start,
                line_end=cls.line_end,
                source_path=module.path,
                kind="class",
            )
    return refs
