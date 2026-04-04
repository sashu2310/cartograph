"""Django signals framework detector.

Detects: @receiver(signal, sender=Model), signal.connect(handler)
"""

from cartograph.graph.models import (
    AsyncBoundaryType,
    EntryPoint,
    EntryPointType,
    FunctionCall,
    ParsedModule,
)


class DjangoSignalDetector:
    framework_id = "django_signals"

    def detect_entry_points(self, module: ParsedModule) -> list[EntryPoint]:
        entries = []
        for func in module.functions:
            if "receiver" in func.decorators:
                signal_info = self._extract_signal_info(func.decorator_details)
                entries.append(
                    EntryPoint(
                        node_id=func.qualified_name,
                        type=EntryPointType.SIGNAL_HANDLER,
                        trigger=f"Signal: {signal_info}"
                        if signal_info
                        else f"Signal handler: {func.name}",
                        description=func.docstring,
                    )
                )
        return entries

    def detect_async_boundary(self, call: FunctionCall) -> AsyncBoundaryType | None:
        return None

    def annotate_call(self, call: FunctionCall) -> dict | None:
        if call.is_method_call and call.name == "connect":
            return {"signal_connection": True, "signal": call.receiver}
        if call.is_method_call and call.name == "send":
            return {"signal_emit": True, "signal": call.receiver}
        return None

    def _extract_signal_info(self, decorator_details: list[dict]) -> str | None:
        for detail in decorator_details:
            if detail.get("name") == "receiver":
                args = detail.get("args", [])
                kwargs = detail.get("kwargs", {})
                parts = []
                if args:
                    parts.append(str(args[0]))
                if "sender" in kwargs:
                    parts.append(f"sender={kwargs['sender']}")
                return ", ".join(parts) if parts else None
        return None
