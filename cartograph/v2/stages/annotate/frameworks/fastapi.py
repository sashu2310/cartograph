"""FastAPI annotator — prefers type-resolved targets, falls back to syntactic matching.

With v2.2's decorator resolution, Stage 2 tells us where each `@app.get`
actually points. If the resolved target starts with `fastapi`, the decorator
is genuinely a FastAPI route — regardless of how the variable `app` was
imported or aliased. The old syntactic gate (`_has_fastapi_import`) remains
as a fallback for legacy caches and unit-test fixtures that exercise the
annotator directly without running Stage 2.
"""

from __future__ import annotations

from cartograph.v2.ir.annotated import ApiRouteLabel, SemanticLabel
from cartograph.v2.ir.resolved import ResolvedDecorator, ResolvedGraph
from cartograph.v2.ir.syntactic import DecoratorSpec, SyntacticModule

_HTTP_METHODS: dict[str, str] = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "delete": "DELETE",
    "head": "HEAD",
    "options": "OPTIONS",
}

_WEBSOCKET_SUFFIXES = frozenset({"websocket", "websocket_route"})


class FastApiAnnotator:
    framework: str = "fastapi"

    def annotate(
        self,
        graph: ResolvedGraph,
        modules: dict[str, SyntacticModule],
    ) -> dict[str, tuple[SemanticLabel, ...]]:
        out: dict[str, list[SemanticLabel]] = {}

        # Type-resolved path: the decorator resolves into fastapi per ty.
        for qname, resolved_decs in graph.decorators_by_target.items():
            label = _match_resolved(resolved_decs)
            if label is not None:
                out.setdefault(qname, []).append(label)

        # Syntactic fallback: kicks in when Stage 2 didn't populate
        # decorators_by_target (legacy cache, test fixtures).
        if not graph.decorators_by_target:
            for module in modules.values():
                if not _has_fastapi_import(module):
                    continue
                for func in module.functions:
                    label = _match_syntactic(func.decorators)
                    if label is not None:
                        out.setdefault(func.qname, []).append(label)

        return {qname: tuple(ls) for qname, ls in out.items()}


def _match_resolved(resolved: tuple[ResolvedDecorator, ...]) -> SemanticLabel | None:
    for rdec in resolved:
        target = rdec.resolved_target or ""
        if not target.startswith("fastapi"):
            continue
        label = _label_for_method_suffix(rdec.name, rdec.args)
        if label is not None:
            return label
    return None


def _match_syntactic(
    decorators: tuple[DecoratorSpec, ...],
) -> SemanticLabel | None:
    for dec in decorators:
        label = _label_for_method_suffix(dec.name, dec.args)
        if label is not None:
            return label
    return None


def _label_for_method_suffix(
    name: str, args: tuple[str, ...]
) -> SemanticLabel | None:
    """`app.get` / `router.post` → ApiRouteLabel. Ignores name tails we don't know."""
    if "." not in name:
        return None
    _, method_attr = name.rsplit(".", 1)
    http_method = _HTTP_METHODS.get(method_attr)
    if http_method:
        path = args[0] if args else "/"
        return ApiRouteLabel(framework="fastapi", method=http_method, path=path)
    if method_attr in _WEBSOCKET_SUFFIXES:
        path = args[0] if args else "/"
        return ApiRouteLabel(framework="fastapi", method="WS", path=path)
    return None


def _has_fastapi_import(module: SyntacticModule) -> bool:
    for imp in module.imports:
        if imp.module and "fastapi" in imp.module:
            return True
        if imp.name in ("FastAPI", "APIRouter"):
            return True
    return False
