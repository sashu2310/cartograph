"""CARTOGRAPH CLI — entry point for code flow exploration."""

import json

import click
from rich.console import Console
from rich.table import Table

from cartograph.config import CartographConfig
from cartograph.parser.ast_parser import parse_directory

console = Console()


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

    modules = parse_directory(config.root_path, config.exclude_dirs)

    table = Table(title="Parsed Modules")
    table.add_column("Module", style="cyan")
    table.add_column("Functions", justify="right", style="green")
    table.add_column("Classes", justify="right", style="yellow")
    table.add_column("Imports", justify="right")

    total_functions = 0
    total_classes = 0

    for module in sorted(modules, key=lambda m: m.module_path):
        func_count = len([f for f in module.functions if f.type != "class"])
        class_count = len(module.classes)
        import_count = len(module.imports)
        total_functions += func_count
        total_classes += class_count

        table.add_row(
            module.module_path,
            str(func_count),
            str(class_count),
            str(import_count),
        )

    console.print(table)
    console.print(
        f"\n[bold]Total:[/] {len(modules)} modules, "
        f"{total_functions} functions, {total_classes} classes\n"
    )

    entry_points = _find_entry_points(modules)
    if entry_points:
        ep_table = Table(title="Discovered Entry Points")
        ep_table.add_column("Type", style="magenta")
        ep_table.add_column("Name", style="cyan")
        ep_table.add_column("File", style="dim")
        ep_table.add_column("Line", justify="right")

        for ep in entry_points:
            ep_table.add_row(ep["type"], ep["name"], ep["file"], str(ep["line"]))

        console.print(ep_table)
        console.print(f"\n[bold]Entry points:[/] {len(entry_points)}\n")


@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.argument("function_name")
@click.option("--output", "-o", type=click.Path(), help="Output JSON file")
@click.option("--depth", "-d", type=int, default=10, help="Max traversal depth")
def trace(path: str, function_name: str, output: str, depth: int):
    """Trace the code flow from a specific function."""
    config = CartographConfig(root_path=path)

    console.print(
        f"\n[bold blue]CARTOGRAPH[/] tracing [green]{function_name}[/]\n"
    )

    modules = parse_directory(config.root_path, config.exclude_dirs)

    target = None
    for module in modules:
        for func in module.functions:
            if func.qualified_name.endswith(function_name) or func.name == function_name:
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

    console.print(f"\n[bold]Call tree:[/]\n")
    _print_call_tree(target, modules, depth=depth, prefix="")

    if output:
        data = _serialize_trace(target, modules, depth)
        with open(output, "w") as f:
            json.dump(data, f, indent=2)
        console.print(f"\n[dim]Output written to {output}[/]")


def _find_entry_points(modules) -> list[dict]:
    """Find all entry points (API routes, Celery tasks, beat schedules)."""
    entry_points = []

    for module in modules:
        for func in module.functions:
            for dec in func.decorators:
                if "api_controller" in dec:
                    entry_points.append({
                        "type": "API Controller",
                        "name": func.name,
                        "file": func.file_path,
                        "line": func.line_start,
                    })

                if "route.get" in dec or "route.post" in dec or "route.patch" in dec or "route.delete" in dec:
                    entry_points.append({
                        "type": f"API Route",
                        "name": func.name,
                        "file": func.file_path,
                        "line": func.line_start,
                    })

                if "celery_app.task" in dec or "shared_task" in dec:
                    entry_points.append({
                        "type": "Celery Task",
                        "name": func.name,
                        "file": func.file_path,
                        "line": func.line_start,
                    })

                if "receiver" in dec:
                    entry_points.append({
                        "type": "Signal Handler",
                        "name": func.name,
                        "file": func.file_path,
                        "line": func.line_start,
                    })

    return entry_points


def _print_call_tree(func, modules, depth=10, prefix="", visited=None):
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

        resolved = _resolve_call(call, func, modules)
        if resolved:
            _print_call_tree(resolved, modules, depth - 1, prefix + "  │ ", visited.copy())

    for branch in func.branches:
        label = "else" if branch.is_else else f"if {branch.condition or '...'}"
        console.print(f"{prefix}[yellow]├─ {label}[/]")
        for call in branch.calls:
            icon = "[blue]⚡[/]" if call.is_async_dispatch else "[green]→[/]"
            receiver_prefix = f"{call.receiver}." if call.receiver else ""
            console.print(f"{prefix}│  {icon} {receiver_prefix}{call.name}()")


def _resolve_call(call, caller_func, modules):
    """Try to resolve a call to a parsed function."""
    for module in modules:
        for func in module.functions:
            if func.name == call.name or func.name.endswith(f".{call.name}"):
                return func
            if call.receiver and func.name == f"{call.receiver}.{call.name}":
                return func
    return None


def _serialize_trace(func, modules, depth) -> dict:
    """Serialize a trace to a JSON-compatible dict."""
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
                "calls": [
                    {"name": c.name, "receiver": c.receiver, "line": c.line}
                    for c in b.calls
                ],
            }
            for b in func.branches
        ],
    }


if __name__ == "__main__":
    main()
