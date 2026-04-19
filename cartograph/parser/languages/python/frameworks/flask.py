"""Flask framework detector.

Detects: @app.route, @app.get/post/put/patch/delete (Flask 2.0+),
@blueprint.route, @blueprint.get/post/..., and Blueprint patterns.
Only activates when the module imports from flask.
"""

from cartograph.graph.models import (
    AsyncBoundaryType,
    EntryPoint,
    EntryPointType,
    FunctionCall,
    ParsedModule,
)

HTTP_METHODS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "delete": "DELETE",
    "head": "HEAD",
    "options": "OPTIONS",
}


class FlaskDetector:
    framework_id = "flask"

    def detect_entry_points(self, module: ParsedModule) -> list[EntryPoint]:
        if not self._has_flask_import(module):
            return []

        entries = []
        for func in module.functions:
            for dec in func.decorators:
                entry = self._match_route(func, dec)
                if entry:
                    entries.append(entry)
                    break
        return entries

    def detect_async_boundary(self, call: FunctionCall) -> AsyncBoundaryType | None:
        return None

    def annotate_call(self, call: FunctionCall) -> dict | None:
        return None

    def _has_flask_import(self, module: ParsedModule) -> bool:
        for imp in module.imports:
            if imp.module and "flask" in imp.module:
                return True
            if imp.name in ("Flask", "Blueprint"):
                return True
        return False

    def _match_route(self, func, decorator: str) -> EntryPoint | None:
        if "." not in decorator:
            return None

        _, method = decorator.rsplit(".", 1)

        # @app.route("/path") or @bp.route("/path")
        # methods kwarg is a list — not extractable from decorator_details
        # (adapter only captures Constant kwargs). Default to ROUTE.
        if method == "route":
            path = self._extract_path(func.decorator_details)
            return EntryPoint(
                node_id=func.qualified_name,
                type=EntryPointType.API_ROUTE,
                trigger=f"ROUTE {path or '/'}",
                description=func.docstring,
            )

        # @app.get("/path"), @bp.post("/path") — Flask 2.0+ shorthand
        http_method = HTTP_METHODS.get(method)
        if http_method:
            path = self._extract_path(func.decorator_details)
            return EntryPoint(
                node_id=func.qualified_name,
                type=EntryPointType.API_ROUTE,
                trigger=f"{http_method} {path or '/'}",
                description=func.docstring,
            )

        # @app.errorhandler(404)
        if method == "errorhandler":
            code = self._extract_error_code(func.decorator_details)
            return EntryPoint(
                node_id=func.qualified_name,
                type=EntryPointType.API_ROUTE,
                trigger=f"ERROR {code or '?'}",
                description=func.docstring,
            )

        return None

    def _extract_path(self, decorator_details: list[dict]) -> str | None:
        for detail in decorator_details:
            args = detail.get("args", [])
            if args and isinstance(args[0], str):
                return args[0]
        return None

    def _extract_error_code(self, decorator_details: list[dict]) -> str | None:
        for detail in decorator_details:
            args = detail.get("args", [])
            if args:
                return str(args[0])
        return None
