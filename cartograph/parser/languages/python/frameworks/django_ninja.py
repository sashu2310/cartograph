"""Django Ninja (django-ninja-extra) framework detector.

Detects: @api_controller, @route.get/post/patch/delete,
@generic_api_controller, URL patterns.
"""

from typing import Optional

from cartograph.graph.models import (
    AsyncBoundaryType,
    EntryPoint,
    EntryPointType,
    FunctionCall,
    ParsedModule,
)


CONTROLLER_DECORATORS = {"api_controller", "generic_api_controller"}

ROUTE_DECORATORS = {
    "route.get": "GET",
    "route.post": "POST",
    "route.patch": "PATCH",
    "route.put": "PUT",
    "route.delete": "DELETE",
}


class DjangoNinjaDetector:
    framework_id = "django_ninja"

    def detect_entry_points(self, module: ParsedModule) -> list[EntryPoint]:
        entries = []
        current_controller_url = ""

        for func in module.functions:
            for dec in func.decorators:
                if dec in CONTROLLER_DECORATORS:
                    url_prefix = self._extract_url(func.decorator_details)
                    current_controller_url = url_prefix or ""
                    entries.append(EntryPoint(
                        node_id=func.qualified_name,
                        type=EntryPointType.API_ROUTE,
                        trigger=f"Controller: {url_prefix or '/'}",
                        description=func.docstring,
                    ))
                    break

                http_method = ROUTE_DECORATORS.get(dec)
                if http_method:
                    route_path = self._extract_url(func.decorator_details)
                    full_path = f"{current_controller_url}{route_path or ''}"
                    entries.append(EntryPoint(
                        node_id=func.qualified_name,
                        type=EntryPointType.API_ROUTE,
                        trigger=f"{http_method} {full_path}",
                        description=func.docstring,
                    ))
                    break

        return entries

    def detect_async_boundary(self, call: FunctionCall) -> Optional[AsyncBoundaryType]:
        return None

    def annotate_call(self, call: FunctionCall) -> Optional[dict]:
        return None

    def _extract_url(self, decorator_details: list[dict]) -> Optional[str]:
        for detail in decorator_details:
            args = detail.get("args", [])
            if args and isinstance(args[0], str):
                return args[0]
        return None
