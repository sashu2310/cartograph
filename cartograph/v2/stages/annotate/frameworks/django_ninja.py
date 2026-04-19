"""Django Ninja annotator — resolved-target first, syntactic fallback.

`@route.get/post/…` inside a class decorated with `@api_controller`. The
prefix from `@api_controller("/prefix")` is joined with each method's path.
"""

from __future__ import annotations

from cartograph.v2.ir.annotated import ApiRouteLabel, SemanticLabel
from cartograph.v2.ir.resolved import ResolvedDecorator, ResolvedGraph
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
_ROUTE_METHOD_TAILS: dict[str, str] = {
    "get": "GET",
    "post": "POST",
    "patch": "PATCH",
    "put": "PUT",
    "delete": "DELETE",
}


class DjangoNinjaAnnotator:
    framework: str = "django_ninja"

    def annotate(
        self,
        graph: ResolvedGraph,
        modules: dict[str, SyntacticModule],
    ) -> dict[str, tuple[SemanticLabel, ...]]:
        out: dict[str, list[SemanticLabel]] = {}

        # Pre-compute class URL prefixes — we still need the module scan for
        # this because class decorators come via DecoratorSpec.args and need
        # to be grouped per class.
        class_prefixes: dict[str, str] = {}
        for module in modules.values():
            class_prefixes.update(_class_url_prefixes(module.classes))

        for module in modules.values():
            for func in module.functions:
                prefix = class_prefixes.get(func.class_name or "", "")
                resolved_decs = graph.decorators_by_target.get(func.qname, ())
                label: SemanticLabel | None = None
                if resolved_decs:
                    label = _match_resolved(resolved_decs, prefix)
                if label is None and _has_ninja_import(module):
                    label = _match_syntactic(func.decorators, prefix)
                if label is not None:
                    out.setdefault(func.qname, []).append(label)

        return {qname: tuple(ls) for qname, ls in out.items()}


def _match_resolved(
    resolved: tuple[ResolvedDecorator, ...], prefix: str
) -> SemanticLabel | None:
    for rdec in resolved:
        target = rdec.resolved_target or ""
        if not (target.startswith("ninja") or target.startswith("django_ninja")):
            continue
        if "." not in rdec.name:
            continue
        _, method_attr = rdec.name.rsplit(".", 1)
        http_method = _ROUTE_METHOD_TAILS.get(method_attr)
        if http_method is None:
            continue
        path = rdec.args[0] if rdec.args else ""
        full_path = f"{prefix}{path}" or "/"
        return ApiRouteLabel(
            framework="django_ninja", method=http_method, path=full_path
        )
    return None


def _match_syntactic(
    decorators: tuple[DecoratorSpec, ...], prefix: str
) -> SemanticLabel | None:
    for dec in decorators:
        http_method = _ROUTE_DECORATORS.get(dec.name)
        if http_method:
            path = dec.args[0] if dec.args else ""
            full_path = f"{prefix}{path}" or "/"
            return ApiRouteLabel(
                framework="django_ninja", method=http_method, path=full_path
            )
    return None


def _class_url_prefixes(
    classes: tuple[SyntacticClass, ...],
) -> dict[str, str]:
    prefixes: dict[str, str] = {}
    for cls in classes:
        for dec in cls.decorators:
            if dec.name in _CONTROLLER_DECORATORS:
                if dec.args:
                    prefixes[cls.name] = dec.args[0]
                break
    return prefixes


def _has_ninja_import(module: SyntacticModule) -> bool:
    for imp in module.imports:
        mod = imp.module or ""
        if mod.startswith("ninja") or mod.startswith("django_ninja"):
            return True
        if imp.name in ("NinjaAPI", "Router", "api_controller"):
            return True
    return False
