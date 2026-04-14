"""FastAPI framework detector.

Detects: @app.get/post/put/patch/delete, @router.get/post/...,
@app.websocket, @app.websocket_route, and APIRouter patterns.
Only activates when the module imports from fastapi.
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

WEBSOCKET_SUFFIXES = {"websocket", "websocket_route"}


class FastAPIDetector:
    framework_id = "fastapi"

    def detect_entry_points(self, module: ParsedModule) -> list[EntryPoint]:
        if not self._has_fastapi_import(module):
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

    def _has_fastapi_import(self, module: ParsedModule) -> bool:
        for imp in module.imports:
            if imp.module and "fastapi" in imp.module:
                return True
            if imp.name in ("FastAPI", "APIRouter"):
                return True
        return False

    def _match_route(self, func, decorator: str) -> EntryPoint | None:
        if "." not in decorator:
            return None

        receiver, method = decorator.rsplit(".", 1)

        # HTTP route: app.get, router.post, etc.
        http_method = HTTP_METHODS.get(method)
        if http_method:
            path = self._extract_path(func.decorator_details)
            return EntryPoint(
                node_id=func.qualified_name,
                type=EntryPointType.API_ROUTE,
                trigger=f"{http_method} {path or '/'}",
                description=func.docstring,
            )

        # WebSocket: app.websocket, app.websocket_route
        if method in WEBSOCKET_SUFFIXES:
            path = self._extract_path(func.decorator_details)
            return EntryPoint(
                node_id=func.qualified_name,
                type=EntryPointType.API_ROUTE,
                trigger=f"WS {path or '/'}",
                description=func.docstring,
            )

        return None

    def _extract_path(self, decorator_details: list[dict]) -> str | None:
        for detail in decorator_details:
            args = detail.get("args", [])
            if args and isinstance(args[0], str):
                return args[0]
        return None
