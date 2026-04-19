"""@celery_app.task / @shared_task / @app.task, gated on celery import."""

from __future__ import annotations

from cartograph.v2.ir.annotated import CeleryTaskLabel, SemanticLabel
from cartograph.v2.ir.resolved import ResolvedGraph
from cartograph.v2.ir.syntactic import DecoratorSpec, SyntacticModule

_TASK_DECORATORS = frozenset({"celery_app.task", "shared_task", "app.task"})


class CeleryAnnotator:
    framework: str = "celery"

    def annotate(
        self,
        graph: ResolvedGraph,
        modules: dict[str, SyntacticModule],
    ) -> dict[str, tuple[SemanticLabel, ...]]:
        out: dict[str, list[SemanticLabel]] = {}
        for module in modules.values():
            if not _has_celery_import(module):
                continue
            for func in module.functions:
                label = _match_task(func.decorators)
                if label is not None:
                    out.setdefault(func.qname, []).append(label)
        return {qname: tuple(ls) for qname, ls in out.items()}


def _has_celery_import(module: SyntacticModule) -> bool:
    for imp in module.imports:
        if imp.module and "celery" in imp.module:
            return True
        if imp.name in ("Celery", "shared_task"):
            return True
    return False


def _match_task(decorators: tuple[DecoratorSpec, ...]) -> SemanticLabel | None:
    for dec in decorators:
        if dec.name in _TASK_DECORATORS:
            queue = dec.kwargs.get("queue")
            bind_raw = dec.kwargs.get("bind", "False")
            bind = bind_raw == "True"
            return CeleryTaskLabel(framework="celery", queue=queue, bind=bind)
    return None
