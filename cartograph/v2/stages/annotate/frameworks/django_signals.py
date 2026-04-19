"""@receiver(signal, sender=...). No import gate — decorator name is distinctive."""

from __future__ import annotations

from cartograph.v2.ir.annotated import DjangoSignalLabel, SemanticLabel
from cartograph.v2.ir.resolved import ResolvedGraph
from cartograph.v2.ir.syntactic import DecoratorSpec, SyntacticModule


class DjangoSignalsAnnotator:
    framework: str = "django_signals"

    def annotate(
        self,
        graph: ResolvedGraph,
        modules: dict[str, SyntacticModule],
    ) -> dict[str, tuple[SemanticLabel, ...]]:
        out: dict[str, list[SemanticLabel]] = {}
        for module in modules.values():
            for func in module.functions:
                label = _match_receiver(func.decorators)
                if label is not None:
                    out.setdefault(func.qname, []).append(label)
        return {qname: tuple(ls) for qname, ls in out.items()}


def _match_receiver(
    decorators: tuple[DecoratorSpec, ...],
) -> SemanticLabel | None:
    for dec in decorators:
        if dec.name != "receiver":
            continue

        # Signal name can be positional or via `signal=` kwarg.
        signal_name: str | None = None
        if dec.args:
            signal_name = dec.args[0]
        elif "signal" in dec.kwargs:
            signal_name = dec.kwargs["signal"]

        sender = dec.kwargs.get("sender")

        # Fall back to "unknown" when the signal name couldn't be captured
        # (e.g., passed as a variable). Still worth emitting a label so the
        # downstream discoverer can promote to SignalHandlerEntry.
        return DjangoSignalLabel(
            framework="django",
            signal_name=signal_name or "unknown",
            sender=sender,
        )
    return None
