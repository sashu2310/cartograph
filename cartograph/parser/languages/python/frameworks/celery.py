"""Celery framework detector for Python.

Detects: @celery_app.task, @shared_task, .delay(), .apply_async(),
chain(), chord(), group(), .s(), .si()
"""

from typing import Optional

from cartograph.graph.models import (
    AsyncBoundaryType,
    EntryPoint,
    EntryPointType,
    FunctionCall,
    ParsedModule,
)


TASK_DECORATORS = {"celery_app.task", "shared_task", "app.task"}

ASYNC_METHODS = {
    "delay": AsyncBoundaryType.CELERY_DELAY,
    "apply_async": AsyncBoundaryType.CELERY_APPLY_ASYNC,
}

ORCHESTRATION_CALLS = {
    "chain": AsyncBoundaryType.CELERY_CHAIN,
    "chord": AsyncBoundaryType.CELERY_CHORD,
    "group": AsyncBoundaryType.CELERY_GROUP,
}

SIGNATURE_METHODS = {"s", "si"}


class CeleryDetector:
    framework_id = "celery"

    def detect_entry_points(self, module: ParsedModule) -> list[EntryPoint]:
        entries = []
        for func in module.functions:
            for dec in func.decorators:
                if dec in TASK_DECORATORS:
                    queue = self._extract_queue(func.decorator_details)
                    trigger = f"Celery task: {func.name}"
                    if queue:
                        trigger += f" (queue={queue})"

                    entries.append(EntryPoint(
                        node_id=func.qualified_name,
                        type=EntryPointType.CELERY_TASK,
                        trigger=trigger,
                        description=func.docstring,
                    ))
                    break
        return entries

    def detect_async_boundary(self, call: FunctionCall) -> Optional[AsyncBoundaryType]:
        if not call.is_method_call:
            return ORCHESTRATION_CALLS.get(call.name)

        if call.name in ASYNC_METHODS:
            return ASYNC_METHODS[call.name]

        if call.name in SIGNATURE_METHODS:
            return AsyncBoundaryType.CELERY_DELAY

        return None

    def annotate_call(self, call: FunctionCall) -> Optional[dict]:
        return None

    def _extract_queue(self, decorator_details: list[dict]) -> Optional[str]:
        for detail in decorator_details:
            kwargs = detail.get("kwargs", {})
            if "queue" in kwargs:
                return kwargs["queue"]
        return None
