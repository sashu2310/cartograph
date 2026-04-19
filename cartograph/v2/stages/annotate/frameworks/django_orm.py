"""ORM method calls emitted as per-site OrmOperationLabels (one label per line)."""

from __future__ import annotations

from cartograph.v2.ir.annotated import OrmOperationLabel, SemanticLabel
from cartograph.v2.ir.resolved import ResolvedGraph
from cartograph.v2.ir.syntactic import (
    CallSite,
    MethodCall,
    SyntacticFunction,
    SyntacticModule,
)

_READ_METHODS = frozenset(
    {
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
)

_WRITE_METHODS = frozenset(
    {
        "create",
        "save",
        "bulk_create",
        "bulk_update",
        "update",
        "get_or_create",
        "update_or_create",
    }
)

_DELETE_METHODS = frozenset({"delete"})


class DjangoOrmAnnotator:
    framework: str = "django_orm"

    def annotate(
        self,
        graph: ResolvedGraph,
        modules: dict[str, SyntacticModule],
    ) -> dict[str, tuple[SemanticLabel, ...]]:
        out: dict[str, list[SemanticLabel]] = {}
        for module in modules.values():
            for func in module.functions:
                labels = _orm_labels_for(func)
                if labels:
                    out.setdefault(func.qname, []).extend(labels)
        return {qname: tuple(ls) for qname, ls in out.items()}


def _orm_labels_for(func: SyntacticFunction) -> list[OrmOperationLabel]:
    """Emit one label per matching call site. No dedup — the IR preserves
    granularity so downstream analyses (N+1, hotspots) keep the information."""
    out: list[OrmOperationLabel] = []
    for site in func.call_sites:
        label = _classify_site(site)
        if label is not None:
            out.append(label)
    return out


def _classify_site(site: CallSite) -> OrmOperationLabel | None:
    call = site.call
    if not isinstance(call, MethodCall):
        return None

    if call.name in _READ_METHODS:
        op: str = "read"
    elif call.name in _WRITE_METHODS:
        op = "write"
    elif call.name in _DELETE_METHODS:
        op = "delete"
    else:
        return None

    model = _extract_model(call.receiver_chain)
    if model is None:
        return None
    return OrmOperationLabel(
        framework="django",
        operation=op,  # type: ignore[arg-type]
        model=model,
        line=call.line,
    )


def _extract_model(chain: tuple[str, ...]) -> str | None:
    """Parse `User.objects.filter` style chains to extract the model name.

    chain is the full access path — e.g. `("User", "objects", "filter")` for
    `User.objects.filter()`. We look for `objects` and take the prior segment.
    Falls back to the first segment if `objects` isn't present.
    """
    if not chain:
        return None
    parts = list(chain)
    if "objects" in parts:
        idx = parts.index("objects")
        if idx > 0:
            return parts[idx - 1]
    return parts[0] if len(parts) >= 1 else None
