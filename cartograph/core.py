"""Core pipeline — parse a project and build its call graph.

Shared by CLI and web viewer. No CLI or rendering dependencies.
"""

from pathlib import Path

from cartograph.config import CartographConfig
from cartograph.graph.call_graph import CallGraph, CallGraphBuilder
from cartograph.graph.models import ProjectIndex
from cartograph.parser.languages.python import PythonAdapter
from cartograph.parser.languages.python.frameworks import (
    CeleryDetector,
    DjangoNinjaDetector,
    DjangoORMDetector,
    DjangoSignalDetector,
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


def parse_and_build(config: CartographConfig) -> tuple[ProjectIndex, CallGraph]:
    """Parse a project and build its call graph. Single entry point for consumers."""
    index = parse_project(config)
    graph = CallGraphBuilder(index).build()
    return index, graph
