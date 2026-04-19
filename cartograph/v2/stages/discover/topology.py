"""Entry points = decorated functions with zero incoming and ≥ 1 outgoing edges.

Labels from Stage 3 promote a generic DiscoveredEntry to a kind-specific
variant (ApiRouteEntry, CeleryTaskEntry, SignalHandlerEntry).
"""

from __future__ import annotations

from cartograph.v2.ir.analyzed import (
    ApiRouteEntry,
    CeleryTaskEntry,
    DiscoveredEntry,
    EntryPoint,
    SignalHandlerEntry,
)
from cartograph.v2.ir.annotated import (
    AnnotatedGraph,
    ApiRouteLabel,
    CeleryTaskLabel,
    DjangoSignalLabel,
)

# Decorators that are language/library features, NOT entry-point indicators.
# Matches v1's _NOISE_DECORATORS set verbatim (keep aligned so benchmark parity
# isn't perturbed by decorator classification drift).
_NOISE_DECORATORS = frozenset(
    {
        # Language features
        "classmethod",
        "staticmethod",
        "property",
        "cached_property",
        "abstractmethod",
        "override",
        "deprecated",
        "classproperty",
        # Dataclass / struct
        "dataclass",
        "dataclass_json",
        "total_ordering",
        # Functools
        "functools.wraps",
        "functools.lru_cache",
        "functools.cached_property",
        "lru_cache",
        "cached_method",
        # Context managers
        "contextmanager",
        "contextlib.contextmanager",
        "contextlib.asynccontextmanager",
        "asynccontextmanager",
        # Testing
        "pytest.fixture",
        "pytest.mark.parametrize",
        # Typing
        "typing.overload",
        "overload",
        # Pydantic validators
        "field_validator",
        "model_validator",
        "computed_field",
        "validator",
        "root_validator",
        # SQLAlchemy
        "hybrid_property",
        "declared_attr",
        "event.listens_for",
        # Observability instrumentation
        "sentry_sdk.trace",
        "sentry_sdk.tracing.trace",
        "metrics.wraps",
    }
)


class TopologyDiscoverer:
    name: str = "topology"

    def discover(self, graph: AnnotatedGraph) -> tuple[EntryPoint, ...]:
        resolved = graph.resolved
        entries: list[EntryPoint] = []

        for qname, func in resolved.functions.items():
            if not self._is_candidate(qname, func, resolved):
                continue

            labels = graph.labels_for(qname)
            entry = self._labeled_entry(qname, labels)
            if entry is None:
                entry = self._discovered_entry(qname, func.decorators)
            if entry is not None:
                entries.append(entry)

        return tuple(entries)

    # ── Decision logic ───────────────────────────────────────────────────

    def _is_candidate(self, qname: str, func, resolved) -> bool:
        # Classes aren't entry points even if they have a decorator and zero
        # incoming edges — a @dataclass with no callers is data, not a route.
        if func.kind == "class":
            return False
        if not func.decorators:
            return False
        # Outgoing edges required.
        if not resolved.callees_by_caller.get(qname):
            return False
        # Zero incoming edges required.
        return not resolved.callers_by_callee.get(qname)

    def _labeled_entry(self, qname: str, labels) -> EntryPoint | None:
        """Promote to a kind-specific EntryPoint if any label matches."""
        for label in labels:
            if isinstance(label, ApiRouteLabel):
                return ApiRouteEntry(
                    qname=qname,
                    method=label.method,
                    path=label.path,
                    description=None,
                )
            if isinstance(label, CeleryTaskLabel):
                return CeleryTaskEntry(
                    qname=qname,
                    queue=label.queue,
                    description=None,
                )
            if isinstance(label, DjangoSignalLabel):
                return SignalHandlerEntry(
                    qname=qname,
                    signal_name=label.signal_name,
                    sender=label.sender,
                    description=None,
                )
        return None

    def _discovered_entry(
        self, qname: str, decorators: tuple[str, ...]
    ) -> EntryPoint | None:
        meaningful = [d for d in decorators if d not in _NOISE_DECORATORS]
        if not meaningful:
            return None
        return DiscoveredEntry(
            qname=qname,
            trigger_decorator=meaningful[0],
            description=None,
        )


__all__ = ["TopologyDiscoverer"]
