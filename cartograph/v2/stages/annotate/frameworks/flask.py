"""Flask @app.route, Flask 2.0 @app.get/post/..., @app.errorhandler. Gated on flask import."""

from __future__ import annotations

from cartograph.v2.ir.annotated import ApiRouteLabel, SemanticLabel
from cartograph.v2.ir.resolved import ResolvedGraph
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


class FlaskAnnotator:
    framework: str = "flask"

    def annotate(
        self,
        graph: ResolvedGraph,
        modules: dict[str, SyntacticModule],
    ) -> dict[str, tuple[SemanticLabel, ...]]:
        out: dict[str, list[SemanticLabel]] = {}
        for module in modules.values():
            if not _has_flask_import(module):
                continue
            for func in module.functions:
                label = _match_route(func.decorators)
                if label is not None:
                    out.setdefault(func.qname, []).append(label)
        return {qname: tuple(ls) for qname, ls in out.items()}


def _has_flask_import(module: SyntacticModule) -> bool:
    for imp in module.imports:
        if imp.module and "flask" in imp.module:
            return True
        if imp.name in ("Flask", "Blueprint"):
            return True
    return False


def _match_route(decorators: tuple[DecoratorSpec, ...]) -> SemanticLabel | None:
    for dec in decorators:
        if "." not in dec.name:
            continue
        _, method_attr = dec.name.rsplit(".", 1)

        if method_attr == "route":
            path = dec.args[0] if dec.args else "/"
            return ApiRouteLabel(framework="flask", method="ROUTE", path=path)

        http_method = _HTTP_METHODS.get(method_attr)
        if http_method:
            path = dec.args[0] if dec.args else "/"
            return ApiRouteLabel(framework="flask", method=http_method, path=path)

        if method_attr == "errorhandler":
            code = dec.args[0] if dec.args else "?"
            return ApiRouteLabel(framework="flask", method="ERROR", path=str(code))

    return None
