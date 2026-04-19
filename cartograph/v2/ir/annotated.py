"""Stage 3 output — graph + framework-specific semantic labels."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Discriminator

from cartograph.v2.ir.base import IR
from cartograph.v2.ir.resolved import ResolvedGraph
from cartograph.v2.ir.syntactic import SyntacticModule


class ApiRouteLabel(IR):
    kind: Literal["api_route"] = "api_route"
    framework: Literal["fastapi", "flask", "django_ninja"]
    method: str  # "GET" | "POST" | …
    path: str  # "/users/{id}"


class CeleryTaskLabel(IR):
    kind: Literal["celery_task"] = "celery_task"
    framework: Literal["celery"] = "celery"
    queue: str | None = None
    bind: bool = False


class CeleryBeatLabel(IR):
    kind: Literal["celery_beat"] = "celery_beat"
    framework: Literal["celery"] = "celery"
    schedule: str


class DjangoSignalLabel(IR):
    kind: Literal["signal_handler"] = "signal_handler"
    framework: Literal["django"] = "django"
    signal_name: str
    sender: str | None = None


class OrmOperationLabel(IR):
    """One label per ORM call site — aggregate at the view layer if needed."""

    kind: Literal["orm_operation"] = "orm_operation"
    framework: Literal["django", "sqlalchemy"]
    operation: Literal["read", "write", "delete"]
    model: str
    line: int


SemanticLabel = Annotated[
    ApiRouteLabel
    | CeleryTaskLabel
    | CeleryBeatLabel
    | DjangoSignalLabel
    | OrmOperationLabel,
    Discriminator("kind"),
]


class AnnotatedGraph(IR):
    resolved: ResolvedGraph
    labels: dict[str, tuple[SemanticLabel, ...]] = {}  # noqa: RUF012 — pydantic deep-copies defaults
    # Keyed by module_name. Default empty so cached ResolvedGraphs still
    # hydrate. Populated fresh by the pipeline each run (not serialized to
    # disk — the data already lives in ExtractCache per-file).
    source_modules: dict[str, SyntacticModule] = {}  # noqa: RUF012

    def labels_for(self, qname: str) -> tuple[SemanticLabel, ...]:
        return self.labels.get(qname, ())
