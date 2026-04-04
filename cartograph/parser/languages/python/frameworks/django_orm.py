"""Django ORM operation detector.

Annotates function calls with read/write/delete semantics
when they match ORM query patterns.
"""

from cartograph.graph.models import (
    AsyncBoundaryType,
    EntryPoint,
    FunctionCall,
    ParsedModule,
)

ORM_READ_METHODS = {
    "filter",
    "get",
    "all",
    "values",
    "values_list",
    "first",
    "last",
    "exists",
    "count",
    "aggregate",
    "annotate",
    "select_related",
    "prefetch_related",
    "order_by",
    "distinct",
    "exclude",
}

ORM_WRITE_METHODS = {
    "create",
    "save",
    "bulk_create",
    "bulk_update",
    "update",
    "get_or_create",
    "update_or_create",
}

ORM_DELETE_METHODS = {"delete"}


class DjangoORMDetector:
    framework_id = "django_orm"

    def detect_entry_points(self, module: ParsedModule) -> list[EntryPoint]:
        return []

    def detect_async_boundary(self, call: FunctionCall) -> AsyncBoundaryType | None:
        return None

    def annotate_call(self, call: FunctionCall) -> dict | None:
        if not call.is_method_call:
            return None

        if call.name in ORM_READ_METHODS:
            model = self._extract_model(call.receiver)
            return {"orm_operation": "read", "model": model}

        if call.name in ORM_WRITE_METHODS:
            model = self._extract_model(call.receiver)
            return {"orm_operation": "write", "model": model}

        if call.name in ORM_DELETE_METHODS:
            model = self._extract_model(call.receiver)
            return {"orm_operation": "delete", "model": model}

        return None

    def _extract_model(self, receiver: str | None) -> str | None:
        if not receiver:
            return None
        # "Sensor.objects" → "Sensor"
        # "self.model.objects" → "model"
        parts = receiver.split(".")
        if "objects" in parts:
            idx = parts.index("objects")
            if idx > 0:
                return parts[idx - 1]
        return parts[0] if parts else None
