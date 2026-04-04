"""CARTOGRAPH CLI — entry point for code flow exploration."""

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

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

        entry_points = fw_registry.detect_all_entry_points(module, adapter.language_id)
        index.entry_points.extend(entry_points)
        fw_registry.annotate_module(module, adapter.language_id)
        index.modules[module.module_path] = module

    return index


@click.group()
def main():
    """CARTOGRAPH — Don't read the code. Read the story."""


@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--include-tests", is_flag=True, help="Include test files in analysis")
def init(path: str, include_tests: bool):
    """Scan and parse a codebase."""
    config = CartographConfig(root_path=path, include_tests=include_tests)
    console.print(f"\n[bold blue]CARTOGRAPH[/] scanning [green]{path}[/]\n")

    index = _parse_project(config)

    # Build call graph
    graph = CallGraphBuilder(index).build()

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
        f"\n[bold]Summary:[/] {index.total_modules} modules, "
        f"{total_functions} functions, {total_classes} classes"
    )
    console.print(
        f"[bold]Call graph:[/] {graph.total_resolved} resolved edges, "
        f"{graph.total_unresolved} unresolved calls"
    )

    # Entry points
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
    """Trace the code flow from a specific function using the call graph."""
    config = CartographConfig(root_path=path)
    console.print(f"\n[bold blue]CARTOGRAPH[/] tracing [green]{function_name}[/]\n")

    index = _parse_project(config)
    graph = CallGraphBuilder(index).build()

    # Find the target function
    target_qname = None
    for qname in graph.functions:
        if qname.endswith(function_name) or function_name in qname:
            target_qname = qname
            break

    if not target_qname:
        console.print(f"[red]Function '{function_name}' not found[/]")
        return

    target = graph.functions[target_qname]

    console.print(f"[green]Found:[/] {target.qualified_name}")
    console.print(f"[dim]File:[/] {target.file_path}:{target.line_start}")
    console.print(f"[dim]Decorators:[/] {', '.join(target.decorators) or 'none'}")

    # Count outgoing edges
    outgoing = graph.get_callees(target_qname)
    cross_file = [e for e in outgoing if e.is_cross_file]
    async_edges = [e for e in outgoing if e.call.is_async_dispatch]

    console.print(
        f"[dim]Outgoing calls:[/] {len(outgoing)} ({len(cross_file)} cross-file, {len(async_edges)} async)"
    )

    # Build rich tree
    tree = Tree(
        f"[bold cyan]{target.name}[/] [dim]{_short_path(target.file_path)}:{target.line_start}[/]"
    )

    _build_call_tree(graph, target_qname, tree, depth=depth, visited=set())

    console.print()
    console.print(tree)
    console.print()

    # Stats
    all_nodes = set()
    all_files = set()
    _collect_reachable(graph, target_qname, all_nodes, all_files, depth=depth)
    console.print(
        f"[bold]Reachable:[/] {len(all_nodes)} functions across {len(all_files)} files"
    )

    if output:
        data = _serialize_graph_trace(graph, target_qname, depth)
        with open(output, "w") as f:
            json.dump(data, f, indent=2)
        console.print(f"[dim]Output written to {output}[/]")


def _build_call_tree(
    graph: CallGraph,
    qname: str,
    tree: Tree,
    depth: int = 10,
    visited: set | None = None,
) -> None:
    """Recursively build a Rich tree from the call graph."""
    if visited is None:
        visited = set()

    if depth <= 0:
        tree.add("[dim]... (max depth)[/]")
        return

    if qname in visited:
        tree.add(f"[dim]↻ cycle → {qname.split('.')[-1]}[/]")
        return

    visited.add(qname)

    edges = graph.get_callees(qname)
    func = graph.functions.get(qname)

    # Direct calls (non-branch)
    for edge in edges:
        callee = graph.functions.get(edge.callee)
        if not callee:
            continue

        if edge.call.is_async_dispatch:
            icon = "[blue]⚡[/]"
            async_label = (
                f" [blue]({edge.call.async_type.value})[/]"
                if edge.call.async_type
                else ""
            )
        else:
            icon = "[green]→[/]"
            async_label = ""

        file_label = ""
        if edge.is_cross_file:
            file_label = f" [dim]{_short_path(callee.file_path)}[/]"

        branch = tree.add(f"{icon} {callee.name}{async_label}{file_label}")
        _build_call_tree(graph, edge.callee, branch, depth - 1, visited.copy())

    # Branches
    if func:
        for br in func.branches:
            label = "else" if br.is_else else f"if {_truncate(br.condition, 60)}"
            branch_node = tree.add(f"[yellow]├─ {label}[/]")
            for call in br.calls:
                # Try to resolve branch calls
                resolved = _resolve_branch_call(graph, qname, call)
                if resolved:
                    callee = graph.functions.get(resolved)
                    if callee:
                        icon = (
                            "[blue]⚡[/]" if call.is_async_dispatch else "[green]→[/]"
                        )
                        sub = branch_node.add(f"{icon} {callee.name}")
                        _build_call_tree(
                            graph, resolved, sub, depth - 1, visited.copy()
                        )
                        continue
                # Unresolved
                receiver_prefix = f"{call.receiver}." if call.receiver else ""
                branch_node.add(
                    f"[dim]→ {receiver_prefix}{call.name}() (unresolved)[/]"
                )


def _resolve_branch_call(graph: CallGraph, caller_qname: str, call) -> str | None:
    """Try to resolve a call from a branch body."""
    for edge in graph.edges:
        if edge.caller == caller_qname and edge.call.name == call.name:
            return edge.callee
    return None


def _collect_reachable(
    graph: CallGraph,
    qname: str,
    nodes: set,
    files: set,
    depth: int = 10,
    visited: set | None = None,
) -> None:
    """Collect all reachable functions and files from a starting point."""
    if visited is None:
        visited = set()
    if depth <= 0 or qname in visited:
        return
    visited.add(qname)

    func = graph.functions.get(qname)
    if func:
        nodes.add(qname)
        files.add(func.file_path)

    for edge in graph.get_callees(qname):
        _collect_reachable(graph, edge.callee, nodes, files, depth - 1, visited)


def _short_path(file_path: str, max_parts: int = 3) -> str:
    """Shorten a file path to last N parts."""
    parts = Path(file_path).parts
    if len(parts) <= max_parts:
        return str(Path(*parts))
    return str(Path(*parts[-max_parts:]))


def _truncate(text: str | None, max_len: int = 60) -> str:
    """Truncate text with ellipsis."""
    if not text:
        return "..."
    return text[:max_len] + "..." if len(text) > max_len else text


def _serialize_graph_trace(graph: CallGraph, root_qname: str, depth: int) -> dict:
    """Serialize a call graph trace to JSON."""
    nodes = {}
    edges = []
    visited = set()

    def _walk(qname: str, d: int):
        if d <= 0 or qname in visited:
            return
        visited.add(qname)

        func = graph.functions.get(qname)
        if func:
            nodes[qname] = {
                "name": func.name,
                "qualified_name": func.qualified_name,
                "file": func.file_path,
                "line_start": func.line_start,
                "line_end": func.line_end,
                "type": func.type.value,
                "decorators": func.decorators,
                "docstring": func.docstring,
                "annotations": func.annotations,
            }

        for edge in graph.get_callees(qname):
            edges.append(
                {
                    "source": edge.caller,
                    "target": edge.callee,
                    "type": "async_dispatch"
                    if edge.call.is_async_dispatch
                    else "calls",
                    "async_type": edge.call.async_type.value
                    if edge.call.async_type
                    else None,
                    "is_cross_file": edge.is_cross_file,
                    "line": edge.call.line,
                }
            )
            _walk(edge.callee, d - 1)

    _walk(root_qname, depth)

    files_touched = list({n["file"] for n in nodes.values()})

    return {
        "entry_point": root_qname,
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "files_touched": files_touched,
            "total_files": len(files_touched),
            "async_boundaries": len(
                [e for e in edges if e["type"] == "async_dispatch"]
            ),
        },
    }


@main.command()
@click.argument("path", type=click.Path(exists=True))
def summary(path: str):
    """Show project summary with call graph stats."""
    config = CartographConfig(root_path=path)
    console.print(f"\n[bold blue]CARTOGRAPH[/] analyzing [green]{path}[/]\n")

    index = _parse_project(config)
    graph = CallGraphBuilder(index).build()

    console.print(f"[bold]Modules:[/]        {index.total_modules}")
    console.print(f"[bold]Functions:[/]      {index.total_functions}")
    console.print(f"[bold]Entry points:[/]   {len(index.entry_points)}")
    console.print(f"[bold]Resolved calls:[/] {graph.total_resolved}")
    console.print(f"[bold]Unresolved:[/]     {graph.total_unresolved}")

    # Breakdown of unresolved reasons
    reasons: dict[str, int] = {}
    for u in graph.unresolved:
        reasons[u.reason] = reasons.get(u.reason, 0) + 1

    if reasons:
        console.print("\n[bold]Unresolved breakdown:[/]")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            console.print(f"  {reason}: {count}")

    # Top functions by outgoing edges
    edge_counts: dict[str, int] = {}
    for edge in graph.edges:
        edge_counts[edge.caller] = edge_counts.get(edge.caller, 0) + 1

    if edge_counts:
        console.print("\n[bold]Top callers (most outgoing calls):[/]")
        top = sorted(edge_counts.items(), key=lambda x: -x[1])[:10]
        for qname, count in top:
            console.print(f"  {count:3d}  {qname}")

    console.print()


if __name__ == "__main__":
    main()
