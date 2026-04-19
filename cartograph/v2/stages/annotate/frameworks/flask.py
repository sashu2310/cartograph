"""Flask annotator — resolved-target first, syntactic fallback.

`@app.route`, `@app.get/post/…` (Flask 2.0), `@app.errorhandler`. Decorator
resolution via LSP lets us distinguish "Flask app with method decorators"
from any other `app.get` call pattern.
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


class FlaskAnnotator:
    framework: str = "flask"

    def annotate(
        self,
        graph: ResolvedGraph,
        modules: dict[str, SyntacticModule],
    ) -> dict[str, tuple[SemanticLabel, ...]]:
        out: dict[str, list[SemanticLabel]] = {}

        for qname, resolved_decs in graph.decorators_by_target.items():
            label = _match_resolved(resolved_decs)
            if label is not None:
                out.setdefault(qname, []).append(label)

        if not graph.decorators_by_target:
            for module in modules.values():
                if not _has_flask_import(module):
                    continue
                for func in module.functions:
                    label = _match_syntactic(func.decorators)
                    if label is not None:
                        out.setdefault(func.qname, []).append(label)

        return {qname: tuple(ls) for qname, ls in out.items()}


def _match_resolved(resolved: tuple[ResolvedDecorator, ...]) -> SemanticLabel | None:
    for rdec in resolved:
        target = rdec.resolved_target or ""
        if not target.startswith("flask"):
            continue
        label = _label_for(rdec.name, rdec.args)
        if label is not None:
            return label
    return None


def _match_syntactic(
    decorators: tuple[DecoratorSpec, ...],
) -> SemanticLabel | None:
    for dec in decorators:
        label = _label_for(dec.name, dec.args)
        if label is not None:
            return label
    return None


def _label_for(name: str, args: tuple[str, ...]) -> SemanticLabel | None:
    if "." not in name:
        return None
    _, method_attr = name.rsplit(".", 1)
    if method_attr == "route":
        path = args[0] if args else "/"
        return ApiRouteLabel(framework="flask", method="ROUTE", path=path)
    http_method = _HTTP_METHODS.get(method_attr)
    if http_method:
        path = args[0] if args else "/"
        return ApiRouteLabel(framework="flask", method=http_method, path=path)
    if method_attr == "errorhandler":
        code = args[0] if args else "?"
        return ApiRouteLabel(framework="flask", method="ERROR", path=str(code))
    return None


def _has_flask_import(module: SyntacticModule) -> bool:
    for imp in module.imports:
        if imp.module and "flask" in imp.module:
            return True
        if imp.name in ("Flask", "Blueprint"):
            return True
    return False
