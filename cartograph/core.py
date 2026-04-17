"""Core pipeline — parse a project and build its call graph.

Shared by CLI and web viewer. No CLI or rendering dependencies.
"""

from pathlib import Path

from cartograph.config import CartographConfig
from cartograph.graph.call_graph import CallGraph, CallGraphBuilder
from cartograph.graph.models import EntryPoint, EntryPointType, NodeType, ProjectIndex
from cartograph.parser.languages.python import PythonAdapter
from cartograph.parser.languages.python.frameworks import (
    CeleryDetector,
    DjangoNinjaDetector,
    DjangoORMDetector,
    DjangoSignalDetector,
    FastAPIDetector,
    FlaskDetector,
)
from cartograph.parser.registry import FrameworkRegistry, LanguageRegistry


def build_registries() -> tuple[LanguageRegistry, FrameworkRegistry]:
    """Build language and framework registries with all available plugins."""
    lang_registry = LanguageRegistry()
    lang_registry.register(PythonAdapter())

    fw_registry = FrameworkRegistry()
    fw_registry.register("python", CeleryDetector())
    fw_registry.register("python", DjangoNinjaDetector())
    fw_registry.register("python", DjangoORMDetector())
    fw_registry.register("python", DjangoSignalDetector())
    fw_registry.register("python", FastAPIDetector())
    fw_registry.register("python", FlaskDetector())

    return lang_registry, fw_registry


def parse_project(config: CartographConfig) -> ProjectIndex:
    """Parse a project using the registry-based pipeline."""
    lang_registry, fw_registry = build_registries()
    index = ProjectIndex(root_path=config.root_path)
    root = Path(config.root_path)

    for source_file in root.rglob("*"):
        if not source_file.is_file():
            continue
        if any(excluded in source_file.parts for excluded in config.exclude_dirs):
            continue

        adapter = lang_registry.get_adapter(str(source_file))
        if not adapter:
            continue

        relative = source_file.relative_to(root)
        module_path = str(relative.with_suffix("")).replace("/", ".")

        module = adapter.parse_file(str(source_file), module_path)
        if not module:
            continue

        entry_points = fw_registry.detect_all_entry_points(module, adapter.language_id)
        index.entry_points.extend(entry_points)
        fw_registry.annotate_module(module, adapter.language_id)
        index.modules[module.module_path] = module

    return index


# Decorators that are language features, not entry points
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
        # Observability instrumentation (not entry points)
        "sentry_sdk.trace",
        "sentry_sdk.tracing.trace",
        "metrics.wraps",
        # Caching
        "cached_method",
        "lru_cache",
    }
)


def _discover_entry_points_from_topology(
    index: ProjectIndex, graph: CallGraph
) -> list[EntryPoint]:
    """Discover entry points from graph topology.

    A function is likely an entry point if:
    1. Zero incoming edges from project code (nobody calls it)
    2. Has at least one outgoing edge (it does something)
    3. Has a decorator (framework registered it for external invocation)
    4. The decorator is not a language feature (classmethod, property, etc.)
    """
    known_eps = {ep.node_id for ep in index.entry_points}
    callee_set: set[str] = set()
    for edge in graph.edges:
        callee_set.add(edge.callee)

    discovered = []
    for qname, func in graph.functions.items():
        if qname in known_eps:
            continue
        if func.type == NodeType.CLASS:
            continue
        if not func.decorators:
            continue
        # Must have outgoing calls
        if not graph.get_callees(qname):
            continue
        # Must have zero incoming edges
        if qname in callee_set:
            continue
        # Filter noise decorators
        meaningful_decorators = [
            d for d in func.decorators if d not in _NOISE_DECORATORS
        ]
        if not meaningful_decorators:
            continue

        decorator_label = meaningful_decorators[0]
        discovered.append(
            EntryPoint(
                node_id=qname,
                type=EntryPointType.DISCOVERED,
                trigger=f"@{decorator_label}",
                description=func.docstring,
            )
        )

    return discovered


def parse_and_build(
    config: CartographConfig, use_cache: bool = True
) -> tuple[ProjectIndex, CallGraph]:
    """Parse a project and build its call graph.

    If use_cache is True (default), loads from .cartograph/ if the cache
    is fresh. Otherwise parses everything and saves the result.
    """
    from cartograph.cache import load_cache, save_cache

    cache_dir = config.cache_dir or str(Path(config.root_path) / ".cartograph")

    # Try loading from cache (skip hash verification — trust the cache)
    if use_cache:
        result = load_cache(cache_dir)
        if result is not None:
            return result

    # Full parse
    index = parse_project(config)
    graph = CallGraphBuilder(index).build()

    # Topology-based entry point discovery
    discovered = _discover_entry_points_from_topology(index, graph)
    index.entry_points.extend(discovered)

    # Save to cache
    if use_cache:
        save_cache(cache_dir, index, graph)

    return index, graph
