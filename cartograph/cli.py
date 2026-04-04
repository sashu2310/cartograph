"""CARTOGRAPH CLI — entry point for code flow exploration."""

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from cartograph.config import CartographConfig
from cartograph.graph.models import ProjectIndex
from cartograph.parser.languages.python import PythonAdapter
from cartograph.parser.languages.python.frameworks import (
    CeleryDetector,
    DjangoNinjaDetector,
    DjangoORMDetector,
    DjangoSignalDetector,
)
from cartograph.parser.registry import FrameworkRegistry, LanguageRegistry

console = Console()


def _build_registries():
    """Build language and framework registries with all available plugins."""
    lang_registry = LanguageRegistry()
    lang_registry.register(PythonAdapter())

    fw_registry = FrameworkRegistry()
    fw_registry.register("python", CeleryDetector())
    fw_registry.register("python", DjangoNinjaDetector())
    fw_registry.register("python", DjangoORMDetector())
    fw_registry.register("python", DjangoSignalDetector())

    return lang_registry, fw_registry


def _parse_project(config: CartographConfig) -> ProjectIndex:
    """Parse a project using the registry-based pipeline."""
    lang_registry, fw_registry = _build_registries()
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

        # Run framework detectors
        entry_points = fw_registry.detect_all_entry_points(module, adapter.language_id)
        index.entry_points.extend(entry_points)

        # Annotate calls with async boundaries and ORM operations
        fw_registry.annotate_module(module, adapter.language_id)

        index.modules[module.module_path] = module

    return index


@click.group()
def main():
    """CARTOGRAPH — Don't read the code. Read the story."""
    pass


@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--include-tests", is_flag=True, help="Include test files in analysis")
def init(path: str, include_tests: bool):
    """Scan and parse a codebase."""
    config = CartographConfig(root_path=path, include_tests=include_tests)
    console.print(f"\n[bold blue]CARTOGRAPH[/] scanning [green]{path}[/]\n")

    index = _parse_project(config)

    # Module table
    table = Table(title="Parsed Modules")
    table.add_column("Module", style="cyan")
    table.add_column("Functions", justify="right", style="green")
    table.add_column("Classes", justify="right", style="yellow")
    table.add_column("Imports", justify="right")

    total_functions = 0
    total_classes = 0

    for mod in sorted(index.modules.values(), key=lambda m: m.module_path):
        func_count = len(mod.functions)
        class_count = len(mod.classes)
        total_functions += func_count
        total_classes += class_count
        table.add_row(
            mod.module_path, str(func_count), str(class_count), str(len(mod.imports))
        )

    console.print(table)
    console.print(
        f"\n[bold]Total:[/] {index.total_modules} modules, "
        f"{total_functions} functions, {total_classes} classes\n"
    )

    # Entry points table
    if index.entry_points:
        ep_table = Table(title="Discovered Entry Points")
        ep_table.add_column("Type", style="magenta")
        ep_table.add_column("Trigger", style="cyan")
        ep_table.add_column("Description", style="dim", max_width=40)

        for ep in index.entry_points:
            ep_table.add_row(ep.type.value, ep.trigger, ep.description or "")

        console.print(ep_table)
        console.print(f"\n[bold]Entry points:[/] {len(index.entry_points)}\n")


@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.argument("function_name")
@click.option("--output", "-o", type=click.Path(), help="Output JSON file")
@click.option("--depth", "-d", type=int, default=10, help="Max traversal depth")
def trace(path: str, function_name: str, output: str, depth: int):
    """Trace the code flow from a specific function."""
    config = CartographConfig(root_path=path)
    console.print(f"\n[bold blue]CARTOGRAPH[/] tracing [green]{function_name}[/]\n")

    index = _parse_project(config)

    # Find the target function
    target = None
    for module in index.modules.values():
        for func in module.functions:
            if (
                func.qualified_name.endswith(function_name)
                or func.name == function_name
            ):
                target = func
                break
        if target:
            break

    if not target:
        console.print(f"[red]Function '{function_name}' not found[/]")
        return

    console.print(f"[green]Found:[/] {target.qualified_name}")
    console.print(f"[dim]File:[/] {target.file_path}:{target.line_start}")
    console.print(f"[dim]Decorators:[/] {', '.join(target.decorators) or 'none'}")
    console.print(f"[dim]Direct calls:[/] {len(target.calls)}")
    console.print(f"[dim]Branches:[/] {len(target.branches)}")
    console.print("\n[bold]Call tree:[/]\n")

    _print_call_tree(target, index, depth=depth, prefix="")

    if output:
        data = _serialize_trace(target)
        with open(output, "w") as f:
            json.dump(data, f, indent=2)
        console.print(f"\n[dim]Output written to {output}[/]")


def _print_call_tree(func, index: ProjectIndex, depth=10, prefix="", visited=None):
    """Recursively print the call tree for a function."""
    if visited is None:
        visited = set()

    if depth <= 0:
        console.print(f"{prefix}[dim]... (max depth reached)[/]")
        return

    if func.qualified_name in visited:
        console.print(f"{prefix}[dim]↻ {func.name} (cycle)[/]")
        return

    visited.add(func.qualified_name)

    for call in func.calls:
        icon = "[blue]⚡[/]" if call.is_async_dispatch else "[green]→[/]"
        receiver_prefix = f"{call.receiver}." if call.receiver else ""
        console.print(f"{prefix}{icon} {receiver_prefix}{call.name}()")

        resolved = _resolve_call(call, index)
        if resolved:
            _print_call_tree(
                resolved, index, depth - 1, prefix + "  │ ", visited.copy()
            )

    for branch in func.branches:
        label = "else" if branch.is_else else f"if {branch.condition or '...'}"
        console.print(f"{prefix}[yellow]├─ {label}[/]")
        for call in branch.calls:
            icon = "[blue]⚡[/]" if call.is_async_dispatch else "[green]→[/]"
            receiver_prefix = f"{call.receiver}." if call.receiver else ""
            console.print(f"{prefix}│  {icon} {receiver_prefix}{call.name}()")


def _resolve_call(call, index: ProjectIndex):
    """Try to resolve a call to a parsed function in the project index."""
    for module in index.modules.values():
        for func in module.functions:
            if func.name == call.name or func.name.endswith(f".{call.name}"):
                return func
            if call.receiver and func.name == f"{call.receiver}.{call.name}":
                return func
    return None


def _serialize_trace(func) -> dict:
    """Serialize a trace to JSON."""
    return {
        "entry": {
            "name": func.qualified_name,
            "file": func.file_path,
            "line": func.line_start,
            "decorators": func.decorators,
            "docstring": func.docstring,
        },
        "calls": [
            {
                "name": c.name,
                "receiver": c.receiver,
                "line": c.line,
                "is_async": c.is_async_dispatch,
                "async_type": c.async_type.value if c.async_type else None,
            }
            for c in func.calls
        ],
        "branches": [
            {
                "condition": b.condition,
                "line": b.line,
                "is_else": b.is_else,
                "calls": [{"name": c.name, "receiver": c.receiver} for c in b.calls],
            }
            for b in func.branches
        ],
    }


if __name__ == "__main__":
    main()
