"""Stage 4 output — the graph with entry points identified."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Discriminator

from cartograph.v2.ir.annotated import AnnotatedGraph
from cartograph.v2.ir.base import IR


class DiscoveredEntry(IR):
    """Topology-based entry: decorator + zero incoming + some outgoing."""

    kind: Literal["discovered"] = "discovered"
    qname: str
    trigger_decorator: str
    description: str | None = None


class ApiRouteEntry(IR):
    kind: Literal["api_route"] = "api_route"
    qname: str
    method: str
    path: str
    description: str | None = None


class CeleryTaskEntry(IR):
    kind: Literal["celery_task"] = "celery_task"
    qname: str
    queue: str | None = None
    description: str | None = None


class SignalHandlerEntry(IR):
    kind: Literal["signal_handler"] = "signal_handler"
    qname: str
    signal_name: str
    sender: str | None = None
    description: str | None = None


EntryPoint = Annotated[
    DiscoveredEntry | ApiRouteEntry | CeleryTaskEntry | SignalHandlerEntry,
    Discriminator("kind"),
]


class AnalyzedGraph(IR):
    annotated: AnnotatedGraph
    entry_points: tuple[EntryPoint, ...] = ()
