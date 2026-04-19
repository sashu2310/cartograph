"""Django Ninja: @route.get/post/... joined with @api_controller prefix. Gated on ninja import."""

from __future__ import annotations

from cartograph.v2.ir.annotated import ApiRouteLabel, SemanticLabel
from cartograph.v2.ir.resolved import ResolvedGraph
from cartograph.v2.ir.syntactic import (
    DecoratorSpec,
    SyntacticClass,
    SyntacticModule,
)

_CONTROLLER_DECORATORS = frozenset({"api_controller", "generic_api_controller"})
_ROUTE_DECORATORS: dict[str, str] = {
    "route.get": "GET",
    "route.post": "POST",
    "route.patch": "PATCH",
    "route.put": "PUT",
    "route.delete": "DELETE",
}


class DjangoNinjaAnnotator:
    framework: str = "django_ninja"

    def annotate(
        self,
        graph: ResolvedGraph,
        modules: dict[str, SyntacticModule],
    ) -> dict[str, tuple[SemanticLabel, ...]]:
        out: dict[str, list[SemanticLabel]] = {}
        for module in modules.values():
            if not _has_ninja_import(module):
                continue
            # Pre-compute per-class URL prefixes from class decorators.
            class_prefixes = _class_url_prefixes(module.classes)

            for func in module.functions:
                label = _match_route(func.decorators, func.class_name, class_prefixes)
                if label is not None:
                    out.setdefault(func.qname, []).append(label)
        return {qname: tuple(ls) for qname, ls in out.items()}


def _has_ninja_import(module: SyntacticModule) -> bool:
    for imp in module.imports:
        mod = imp.module or ""
        if mod.startswith("ninja") or mod.startswith("django_ninja"):
            return True
        if imp.name in ("NinjaAPI", "Router", "api_controller"):
            return True
    return False


def _class_url_prefixes(
    classes: tuple[SyntacticClass, ...],
) -> dict[str, str]:
    """Extract URL prefixes from @api_controller / @generic_api_controller."""
    prefixes: dict[str, str] = {}
    for cls in classes:
        for dec in cls.decorators:
            if dec.name in _CONTROLLER_DECORATORS:
                if dec.args:
                    prefixes[cls.name] = dec.args[0]
                break
    return prefixes


def _match_route(
    decorators: tuple[DecoratorSpec, ...],
    class_name: str | None,
    class_prefixes: dict[str, str],
) -> SemanticLabel | None:
    prefix = class_prefixes.get(class_name or "", "")
    for dec in decorators:
        http_method = _ROUTE_DECORATORS.get(dec.name)
        if http_method:
            path = dec.args[0] if dec.args else ""
            full_path = f"{prefix}{path}" or "/"
            return ApiRouteLabel(
                framework="django_ninja", method=http_method, path=full_path
            )
    return None
