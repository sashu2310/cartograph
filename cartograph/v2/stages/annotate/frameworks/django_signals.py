"""Django signals annotator — resolved-target first, syntactic fallback.

`@receiver(signal, sender=…)`. Resolving `receiver` lets us confirm it's
actually `django.dispatch.receiver` and not some other `receiver` decorator
from an unrelated library.
"""

from __future__ import annotations

from cartograph.v2.ir.annotated import DjangoSignalLabel, SemanticLabel
from cartograph.v2.ir.resolved import ResolvedDecorator, ResolvedGraph
from cartograph.v2.ir.syntactic import DecoratorSpec, SyntacticModule


class DjangoSignalsAnnotator:
    framework: str = "django_signals"

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
                if not _has_dispatch_import(module):
                    continue
                for func in module.functions:
                    label = _match_syntactic(func.decorators)
                    if label is not None:
                        out.setdefault(func.qname, []).append(label)

        return {qname: tuple(ls) for qname, ls in out.items()}


def _match_resolved(resolved: tuple[ResolvedDecorator, ...]) -> SemanticLabel | None:
    for rdec in resolved:
        target = rdec.resolved_target or ""
        if not target.startswith("django.dispatch") and not target.startswith("django"):
            continue
        if rdec.name != "receiver":
            continue
        return _label_for(rdec)
    return None


def _match_syntactic(
    decorators: tuple[DecoratorSpec, ...],
) -> SemanticLabel | None:
    for dec in decorators:
        if dec.name != "receiver":
            continue
        return _label_for(dec)
    return None


def _label_for(spec: ResolvedDecorator | DecoratorSpec) -> SemanticLabel:
    signal_name: str | None = None
    if spec.args:
        signal_name = spec.args[0]
    elif "signal" in spec.kwargs:
        signal_name = spec.kwargs["signal"]
    sender = spec.kwargs.get("sender")
    return DjangoSignalLabel(
        framework="django",
        signal_name=signal_name or "unknown",
        sender=sender,
    )


def _has_dispatch_import(module: SyntacticModule) -> bool:
    for imp in module.imports:
        mod = imp.module or ""
        if mod.startswith("django.dispatch"):
            return True
        if mod == "django.dispatch" and imp.name == "receiver":
            return True
    return False
