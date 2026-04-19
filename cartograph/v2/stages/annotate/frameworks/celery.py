"""Celery annotator — resolved-target first, syntactic fallback.

`@celery_app.task`, `@shared_task`, `@app.task`. The resolved target — any
symbol inside the `celery` package — is a stronger signal than the name
string, which can collide with unrelated frameworks that also use `.task`.
"""

from __future__ import annotations

from cartograph.v2.ir.annotated import CeleryTaskLabel, SemanticLabel
from cartograph.v2.ir.resolved import ResolvedDecorator, ResolvedGraph
from cartograph.v2.ir.syntactic import DecoratorSpec, SyntacticModule

_TASK_DECORATOR_TAILS = frozenset({"task", "shared_task"})
_TASK_DECORATOR_NAMES = frozenset({"celery_app.task", "shared_task", "app.task"})


class CeleryAnnotator:
    framework: str = "celery"

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
                if not _has_celery_import(module):
                    continue
                for func in module.functions:
                    label = _match_syntactic(func.decorators)
                    if label is not None:
                        out.setdefault(func.qname, []).append(label)

        return {qname: tuple(ls) for qname, ls in out.items()}


def _match_resolved(resolved: tuple[ResolvedDecorator, ...]) -> SemanticLabel | None:
    for rdec in resolved:
        target = rdec.resolved_target or ""
        if not target.startswith("celery"):
            continue
        # Target is in celery; any decorator here is a task registration.
        return _build_label(rdec.kwargs)
    return None


def _match_syntactic(
    decorators: tuple[DecoratorSpec, ...],
) -> SemanticLabel | None:
    for dec in decorators:
        if dec.name in _TASK_DECORATOR_NAMES or (
            "." in dec.name and dec.name.rsplit(".", 1)[-1] in _TASK_DECORATOR_TAILS
        ):
            return _build_label(dec.kwargs)
    return None


def _build_label(kwargs: dict[str, str]) -> SemanticLabel:
    queue = kwargs.get("queue")
    bind_raw = kwargs.get("bind", "False")
    bind = bind_raw == "True"
    return CeleryTaskLabel(framework="celery", queue=queue, bind=bind)


def _has_celery_import(module: SyntacticModule) -> bool:
    for imp in module.imports:
        if imp.module and "celery" in imp.module:
            return True
        if imp.name in ("Celery", "shared_task"):
            return True
    return False
