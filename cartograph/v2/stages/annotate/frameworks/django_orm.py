"""ORM method calls emitted as per-site OrmOperationLabels.

Two-step guard against false positives:
  1. Project-level gate — if no module imports `django.db.models`, the annotator
     is a no-op. Kills non-Django noise entirely.
  2. Verified receivers — inside a Django project, we label a call site only
     when the receiver resolves to a known Django Model class. Two shapes we
     accept:
       a. `Model.objects.X()`  — where `Model` is a project class that
          transitively inherits from `django.db.models.Model`.
       b. `self.X()`           — where the enclosing method's class is itself
          such a Model.
     Anything else (dict.get(), random local var named `.save()`'d) is dropped,
     with no guessing.

Model-class identification walks `SyntacticClass.bases` syntactically (we look
for names ending in `.Model` or equal to `Model`) and takes the transitive
closure over project-internal inheritance. This stays cheap (O(classes)) and
doesn't require running a type checker over every base.
"""

from __future__ import annotations

from cartograph.v2.ir.annotated import OrmOperationLabel, SemanticLabel
from cartograph.v2.ir.resolved import ResolvedGraph
from cartograph.v2.ir.syntactic import (
    CallSite,
    MethodCall,
    SyntacticClass,
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

# Syntactic matches for django.db.models.Model in a class base list.
_MODEL_BASE_NAMES = frozenset({"Model", "models.Model", "django.db.models.Model"})


class DjangoOrmAnnotator:
    framework: str = "django_orm"

    def annotate(
        self,
        graph: ResolvedGraph,
        modules: dict[str, SyntacticModule],
    ) -> dict[str, tuple[SemanticLabel, ...]]:
        if not _project_uses_django_models(modules):
            return {}

        model_names = _collect_django_model_class_names(modules)
        if not model_names:
            return {}

        out: dict[str, list[SemanticLabel]] = {}
        for module in modules.values():
            for func in module.functions:
                labels = _orm_labels_for(func, model_names)
                if labels:
                    out.setdefault(func.qname, []).extend(labels)
        return {qname: tuple(ls) for qname, ls in out.items()}


def _project_uses_django_models(modules: dict[str, SyntacticModule]) -> bool:
    """True if *any* module imports something from django.db.models.

    We accept the common shapes:
        from django.db import models
        from django.db.models import Model, ...
        import django.db.models
    """
    for module in modules.values():
        for imp in module.imports:
            mod = imp.module or ""
            if mod == "django.db" and imp.name == "models":
                return True
            if mod.startswith("django.db.models"):
                return True
            if mod == "django.db.models":
                return True
    return False


def _collect_django_model_class_names(
    modules: dict[str, SyntacticModule],
) -> frozenset[str]:
    """Short names of classes that transitively inherit from django.db.models.Model.

    Returns short names (e.g. `"User"`), not qnames — the receiver in a call
    chain like `User.objects.filter()` is the short name as it appears in source.
    """
    all_classes: dict[str, SyntacticClass] = {}
    for module in modules.values():
        for cls in module.classes:
            # A name collision (two `User` classes in different modules) is
            # resolved by last-wins; in practice the cost of over-matching is
            # far smaller than the cost of missing a Model.
            all_classes[cls.name] = cls

    seeds: set[str] = set()
    for name, cls in all_classes.items():
        if _is_direct_django_model(cls.bases):
            seeds.add(name)

    # Transitive closure: anything inheriting (by name) from a seed is also a Model.
    changed = True
    while changed:
        changed = False
        for name, cls in all_classes.items():
            if name in seeds:
                continue
            for base in cls.bases:
                base_short = base.rsplit(".", 1)[-1]
                if base_short in seeds:
                    seeds.add(name)
                    changed = True
                    break

    return frozenset(seeds)


def _is_direct_django_model(bases: tuple[str, ...]) -> bool:
    for base in bases:
        if base in _MODEL_BASE_NAMES:
            return True
        # Allow `foo.Model` from idiosyncratic imports.
        if base.endswith(".Model"):
            return True
    return False


def _orm_labels_for(
    func: SyntacticFunction,
    model_names: frozenset[str],
) -> list[OrmOperationLabel]:
    """One label per verified call site — no dedup, granularity is deliberate."""
    out: list[OrmOperationLabel] = []
    for site in func.call_sites:
        label = _classify_site(site, func.class_name, model_names)
        if label is not None:
            out.append(label)
    return out


def _classify_site(
    site: CallSite,
    enclosing_class: str | None,
    model_names: frozenset[str],
) -> OrmOperationLabel | None:
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

    model = _resolve_receiver_model(call.receiver_chain, enclosing_class, model_names)
    if model is None:
        return None
    return OrmOperationLabel(
        framework="django",
        operation=op,  # type: ignore[arg-type]
        model=model,
        line=call.line,
    )


def _resolve_receiver_model(
    chain: tuple[str, ...],
    enclosing_class: str | None,
    model_names: frozenset[str],
) -> str | None:
    """Return the Model class name if the receiver resolves to one, else None.

    Accepted receiver shapes:
        (Model, objects, <method>)            → Model
        (Model, objects, ...intermediate..., <method>)  → Model
        (self, <method>)                      → enclosing_class if it's a Model
    """
    if not chain:
        return None

    # Pattern: self.<method>() — inside a Model method.
    if chain[0] == "self" and len(chain) == 2:
        if enclosing_class and enclosing_class in model_names:
            return enclosing_class
        return None

    # Pattern: Model.objects.<method>() — manager call.
    if "objects" in chain:
        idx = chain.index("objects")
        if idx > 0 and chain[idx - 1] in model_names:
            return chain[idx - 1]
        return None

    return None
