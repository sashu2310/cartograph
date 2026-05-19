"""CARTOGRAPH CLI — entry point for code flow exploration."""

import json
from collections import defaultdict, deque
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from cartograph.config import CartographConfig
from cartograph.core import parse_and_build
from cartograph.graph.call_graph import CallGraph
from cartograph.graph.models import ProjectIndex

console = Console()
stderr_console = Console(stderr=True)

LAST_PROJECT_FILE = Path.home() / ".cartograph" / "last_project"


def _save_last_project(path: str) -> None:
    """Remember the last scanned project path."""
    LAST_PROJECT_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_PROJECT_FILE.write_text(str(Path(path).resolve()), encoding="utf-8")


def _get_last_project() -> str | None:
    """Get the last scanned project path."""
    if LAST_PROJECT_FILE.exists():
        path = LAST_PROJECT_FILE.read_text(encoding="utf-8").strip()
        if Path(path).exists():
            return path
    return None


def _resolve_path(path: str | None) -> str:
    """Resolve project path — use argument if given, otherwise last scanned."""
    if path and Path(path).exists():
        return str(Path(path).resolve())
    last = _get_last_project()
    if last:
        stderr_console.print(f"[dim]Using: {last}[/]")
        return last
    console.print("[red]No project path given and no previous scan found.[/]")
    console.print("Run: [bold]carto scan /path/to/project[/] first.")
    raise SystemExit(1)


def _resolve_path_and_arg(path: str | None, arg: str | None) -> tuple[str, str | None]:
    """For commands with path + second arg (function_name, query).

    If path doesn't exist as a filesystem path, treat it as the arg
    and use last scanned project.
    """
    if path and Path(path).exists():
        return str(Path(path).resolve()), arg
    # path is actually the function name — shift args
    real_arg = path
    last = _get_last_project()
    if last:
        stderr_console.print(f"[dim]Using: {last}[/]")
        return last, real_arg
    console.print("[red]No project path given and no previous scan found.[/]")
    console.print("Run: [bold]carto scan /path/to/project[/] first.")
    raise SystemExit(1)


def _find_function(graph: CallGraph, name: str) -> str | None:
    """Find a function by name — prefer exact suffix, then substring."""
    # Exact qualified name
    if name in graph.functions:
        return name
    # Exact suffix match (e.g., "ConsumerPlugin.run" matches "documents.consumer.ConsumerPlugin.run")
    for qname in graph.functions:
        if qname.endswith(f".{name}") or qname == name:
            return qname
    # Substring fallback
    for qname in graph.functions:
        if name in qname:
            return qname
    return None


@click.group()
def main():
    """CARTOGRAPH — Don't read the code. Read the story."""


@main.command()
@click.argument("path", required=False, default=None)
@click.option("--include-tests", is_flag=True, help="Include test files in analysis")
def init(path: str, include_tests: bool):
    """Scan and parse a codebase."""
    path = _resolve_path(path)
    config = CartographConfig(root_path=path, include_tests=include_tests)
    console.print(f"\n[bold blue]CARTOGRAPH[/] scanning [green]{path}[/]\n")

    index, graph = parse_and_build(config)

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
@click.argument("path", required=False, default=None)
@click.argument("function_name", required=False, default=None)
@click.option("--output", "-o", type=click.Path(), help="Output JSON file")
@click.option("--depth", "-d", type=int, default=10, help="Max traversal depth")
def trace(path: str, function_name: str, output: str, depth: int):
    """Trace the code flow from a specific function using the call graph."""
    path, function_name = _resolve_path_and_arg(path, function_name)
    config = CartographConfig(root_path=path)
    console.print(f"\n[bold blue]CARTOGRAPH[/] tracing [green]{function_name}[/]\n")

    _index, graph = parse_and_build(config)

    target_qname = _find_function(graph, function_name)
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
@click.argument("path", required=False, default=None)
def summary(path: str):
    """Show project summary with call graph stats."""
    path = _resolve_path(path)
    config = CartographConfig(root_path=path)
    console.print(f"\n[bold blue]CARTOGRAPH[/] analyzing [green]{path}[/]\n")

    index, graph = parse_and_build(config)

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


@main.command()
@click.argument("path", required=False, default=None)
@click.option("--port", "-p", default=3333, type=int, help="Port to serve on")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--include-tests", is_flag=True, help="Include test files")
def serve(path: str, port: int, host: str, include_tests: bool):
    """Launch interactive web viewer for code flow exploration."""
    path = _resolve_path(path)
    import uvicorn

    from cartograph.web import create_app

    config = CartographConfig(root_path=path, include_tests=include_tests)
    project_name = Path(path).resolve().name

    console.print(f"\n[bold blue]CARTOGRAPH[/] parsing [green]{path}[/] ...\n")
    index, graph = parse_and_build(config)

    console.print(
        f"  [dim]Parsed:[/] {index.total_modules} modules, "
        f"{index.total_functions} functions, "
        f"{graph.total_resolved} edges, "
        f"{len(index.entry_points)} entry points\n"
    )

    app = create_app(graph, index, project_name)

    console.print(
        f"[bold green]Ready.[/] Open [link=http://{host}:{port}]http://{host}:{port}[/link]\n"
    )

    uvicorn.run(app, host=host, port=port, log_level="warning")


def _find_common_prefix(paths: list[str], threshold: float = 0.7) -> list[str]:
    """Find the longest common module prefix shared by >threshold of paths.

    Returns the prefix parts to skip. For ['src.prefect.server.api.x',
    'src.prefect.cli.y', 'examples.z'], returns ['src', 'prefect'] because
    >70% of paths share that prefix.
    """
    if not paths:
        return []
    split_paths = [p.split(".") for p in paths]
    prefix = []
    for depth in range(min(len(p) for p in split_paths)):
        parts_at_depth = [p[depth] for p in split_paths]
        counts: dict[str, int] = defaultdict(int)
        for part in parts_at_depth:
            counts[part] += 1
        most_common = max(counts.items(), key=lambda x: x[1])
        if most_common[1] / len(paths) >= threshold:
            prefix.append(most_common[0])
        else:
            break
    return prefix


# Module names that are structural, not domain-meaningful
_STRUCTURAL_NAMES = frozenset(
    {
        "endpoints",
        "tasks",
        "views",
        "handlers",
        "service",
        "services",
        "api",
        "routes",
        "routers",
        "commands",
        "signals",
        "receivers",
        "models",
        "schemas",
        "serializers",
        "utils",
        "helpers",
        "core",
        "base",
        "mixins",
        "middleware",
        "admin",
        "management",
    }
)


def _group_entry_points(index: ProjectIndex, graph: CallGraph) -> list[dict]:
    """Group entry points by domain module. Returns sorted list of flow groups."""
    all_ids = [ep.node_id for ep in index.entry_points]

    # Find common prefix shared by majority (e.g., ['src', 'prefect'])
    prefix = _find_common_prefix(all_ids)

    # If after stripping, the next level is still a single dominant group,
    # strip one more level (the project name, e.g., 'prefect' in 'src.prefect')
    prefix_len = len(prefix)
    next_parts = [
        p.split(".")[prefix_len] for p in all_ids if len(p.split(".")) > prefix_len
    ]
    if next_parts:
        next_counts: dict[str, int] = defaultdict(int)
        for p in next_parts:
            next_counts[p] += 1
        top_next = max(next_counts.items(), key=lambda x: x[1])
        if top_next[1] / len(next_parts) >= 0.6:
            # The next level is dominated by one name — strip it too
            prefix.append(top_next[0])
            prefix_len += 1

    groups: dict[str, list] = defaultdict(list)
    for ep in index.entry_points:
        parts = ep.node_id.split(".")
        # Strip the common prefix
        domain_parts = parts[prefix_len:]
        # Skip structural names to find the domain
        while domain_parts and domain_parts[0] in _STRUCTURAL_NAMES:
            domain_parts = domain_parts[1:]
        group = (
            domain_parts[0]
            if domain_parts
            else parts[-2]
            if len(parts) >= 2
            else parts[0]
        )
        groups[group].append(ep)

    result = []
    for group, eps in sorted(groups.items(), key=lambda x: -len(x[1])):
        # Find deepest entry point
        max_reachable = 0
        deepest_name = ""
        for ep in eps:
            visited: set[str] = set()
            queue: deque[tuple[str, int]] = deque([(ep.node_id, 0)])
            while queue:
                qn, d = queue.popleft()
                if qn in visited or d > 5:
                    continue
                visited.add(qn)
                for edge in graph.get_callees(qn):
                    queue.append((edge.callee, d + 1))
            if len(visited) > max_reachable:
                max_reachable = len(visited)
                deepest_name = ep.node_id.split(".")[-1]

        # Entry point type breakdown
        type_counts: dict[str, int] = defaultdict(int)
        for ep in eps:
            type_counts[ep.type.value] += 1

        result.append(
            {
                "name": group,
                "count": len(eps),
                "types": dict(type_counts),
                "deepest_name": deepest_name,
                "deepest_reachable": max_reachable,
                "triggers": [ep.trigger for ep in eps[:3]],
                "entry_points": eps,
            }
        )

    return result


@main.command()
@click.argument("path", type=click.Path(exists=True))
def scan(path: str):
    """Scan a codebase, discover flows, and save to .cartograph/ cache.

    This is the first step. Run once, then use entries/trace/explain
    without re-parsing.
    """
    config = CartographConfig(root_path=path)
    console.print(f"\n[bold blue]CARTOGRAPH[/] scanning [green]{path}[/]\n")

    _save_last_project(path)
    index, graph = parse_and_build(config, use_cache=False)

    total_funcs = sum(len(m.functions) for m in index.modules.values())
    console.print("[bold green]Scan complete.[/]")
    console.print(
        f"  {len(index.modules)} modules · {total_funcs} functions · "
        f"{len(index.entry_points)} entry points · {graph.total_resolved} resolved calls\n"
    )

    # Group into flows
    flow_groups = _group_entry_points(index, graph)

    console.print("[bold]Discovered Flows:[/]\n")
    for i, grp in enumerate(flow_groups[:15], 1):
        type_str = ", ".join(
            f"{v} {k}" for k, v in sorted(grp["types"].items(), key=lambda x: -x[1])
        )
        triggers = ", ".join(grp["triggers"])
        if grp["count"] > 3:
            triggers += f", +{grp['count'] - 3} more"

        console.print(
            f"  [bold cyan]{i:>2}.[/] [bold]{grp['name']}[/] "
            f"({grp['count']} entry points: {type_str})"
        )
        console.print(f"      {triggers}")
        if grp["deepest_reachable"] > 1:
            console.print(
                f"      [dim]Deepest: {grp['deepest_name']} → "
                f"{grp['deepest_reachable']} functions[/]"
            )
        console.print()

    if len(flow_groups) > 15:
        console.print(f"  [dim]...and {len(flow_groups) - 15} more groups[/]\n")

    console.print(f"  [dim]Cached to: {config.cache_dir}[/]\n")
    console.print("[bold]Next steps:[/]")
    console.print("  carto explain              [dim]← explain the whole codebase[/]")
    console.print('  carto explain "function"   [dim]← explain a specific flow[/]')
    console.print('  carto trace "function"     [dim]← trace a call tree[/]')
    console.print("  carto entries              [dim]← list all entry points[/]")
    console.print("  carto context | claude     [dim]← pipe to any LLM[/]")


@main.command()
@click.argument("path", required=False, default=None)
@click.option(
    "--type",
    "-t",
    "ep_type",
    default=None,
    help="Filter by type (api_route, celery_task, signal_handler, discovered)",
)
def entries(path: str, ep_type: str | None):
    """List all entry points in the codebase."""
    path = _resolve_path(path)
    config = CartographConfig(root_path=path)
    index, _graph = parse_and_build(config)

    eps = index.entry_points
    if ep_type:
        eps = [ep for ep in eps if ep.type.value == ep_type]

    # Group by type
    from collections import defaultdict

    by_type: dict[str, list] = defaultdict(list)
    for ep in eps:
        by_type[ep.type.value].append(ep)

    console.print(f"\n[bold blue]CARTOGRAPH[/] — {len(eps)} entry points\n")

    for type_name, type_eps in sorted(by_type.items()):
        table = Table(title=f"{type_name.upper()} ({len(type_eps)})", show_lines=False)
        table.add_column("Trigger", style="cyan", max_width=50)
        table.add_column("Function", style="green", max_width=60)
        table.add_column("Description", style="dim", max_width=40)

        for ep in sorted(type_eps, key=lambda e: e.trigger):
            short_name = ep.node_id.split(".")[-1] if "." in ep.node_id else ep.node_id
            desc = (ep.description or "")[:40]
            table.add_row(ep.trigger, short_name, desc)

        console.print(table)
        console.print()


@main.command()
@click.argument("path", required=False, default=None)
@click.argument("query", required=False, default=None)
@click.option("--limit", "-l", default=20, help="Max results")
def search(path: str, query: str, limit: int):
    """Search functions by name."""
    path, query = _resolve_path_and_arg(path, query)
    config = CartographConfig(root_path=path)
    _index, graph = parse_and_build(config)

    query_lower = query.lower()
    results = []
    for qname, func in graph.functions.items():
        if query_lower in qname.lower() or query_lower in func.name.lower():
            results.append(func)
            if len(results) >= limit:
                break

    console.print(
        f"\n[bold blue]CARTOGRAPH[/] — {len(results)} results for '{query}'\n"
    )

    table = Table(show_lines=False)
    table.add_column("Function", style="green")
    table.add_column("Type", style="cyan")
    table.add_column("File", style="dim")

    for func in results:
        short_file = "/".join(func.file_path.split("/")[-3:])
        table.add_row(
            func.qualified_name, func.type.value, f"{short_file}:{func.line_start}"
        )

    console.print(table)


@main.command()
@click.argument("path", required=False, default=None)
@click.argument("function_name", required=False, default=None)
def callers(path: str, function_name: str):
    """Show who calls a function (reverse lookup)."""
    path, function_name = _resolve_path_and_arg(path, function_name)
    config = CartographConfig(root_path=path)
    _index, graph = parse_and_build(config)

    target = _find_function(graph, function_name)
    if not target:
        console.print(f"[red]Function '{function_name}' not found[/]")
        return

    caller_edges = graph.get_callers(target)
    console.print(f"\n[bold blue]CARTOGRAPH[/] — callers of [green]{target}[/]\n")

    if not caller_edges:
        console.print("[dim]No callers found (this may be an entry point).[/]")
        return

    table = Table(show_lines=False)
    table.add_column("Caller", style="green")
    table.add_column("Line", style="dim")
    table.add_column("Cross-file", style="cyan")
    table.add_column("Condition", style="yellow")

    for edge in caller_edges:
        table.add_row(
            edge.caller,
            str(edge.call.line),
            "✓" if edge.is_cross_file else "",
            edge.condition or "",
        )

    console.print(table)


@main.command()
@click.argument("path", required=False, default=None)
@click.argument("function_name", required=False)
@click.option("--depth", "-d", type=int, default=5, help="Max traversal depth")
def explain(path: str, function_name: str | None, depth: int):
    """Explain a codebase or a specific flow using an LLM.

    Without function_name: explains the whole codebase (skeleton summary).
    With function_name: explains that specific flow.
    """
    path, function_name = _resolve_path_and_arg(path, function_name)
    from cartograph.llm import get_llm_provider

    config = CartographConfig(root_path=path)
    index, graph = parse_and_build(config)

    try:
        provider = get_llm_provider()
    except Exception as e:
        console.print(f"[red]LLM error:[/] {e}")
        console.print(
            "[dim]Set CARTOGRAPH_LLM_PROVIDER (claude/openai/ollama) "
            "and the corresponding API key.[/]"
        )
        return

    if function_name is None:
        # Codebase-level explanation
        _explain_codebase(index, graph, provider)
    else:
        # Scoped flow explanation
        _explain_flow(graph, function_name, provider, depth)


def _explain_codebase(index, graph, provider):
    """Generate a codebase-level explanation from the skeleton."""
    from collections import Counter

    console.print("\n[bold blue]CARTOGRAPH[/] explaining codebase\n")
    console.print("[dim]Building skeleton...[/]")

    # Build a concise skeleton for the LLM
    ep_by_type = Counter(ep.type.value for ep in index.entry_points)
    top_callers = sorted(
        [(qn, len(graph.get_callees(qn))) for qn in graph.functions],
        key=lambda x: -x[1],
    )[:15]

    # Sample entry points (up to 5 per type)
    ep_samples = {}
    for ep in index.entry_points:
        t = ep.type.value
        if t not in ep_samples:
            ep_samples[t] = []
        if len(ep_samples[t]) < 5:
            ep_samples[t].append(f"{ep.trigger} → {ep.node_id.split('.')[-1]}")

    skeleton = f"""## Codebase Skeleton

Modules: {len(index.modules)}
Functions: {sum(len(m.functions) for m in index.modules.values())}
Entry points: {len(index.entry_points)}
Resolved call edges: {graph.total_resolved}

### Entry points by type
"""
    for t, count in ep_by_type.most_common():
        skeleton += f"\n**{t}** ({count}):\n"
        for sample in ep_samples.get(t, []):
            skeleton += f"  - {sample}\n"

    skeleton += "\n### Top functions by outgoing calls\n"
    for qn, count in top_callers:
        skeleton += f"  {count:>3}  {qn}\n"

    # Module structure
    top_packages = Counter()
    for mp in index.modules:
        parts = mp.split(".")
        if len(parts) >= 2:
            top_packages[parts[0] + "." + parts[1]] += 1

    skeleton += "\n### Top packages by module count\n"
    for pkg, count in top_packages.most_common(15):
        skeleton += f"  {count:>3}  {pkg}\n"

    system = """You are CARTOGRAPH. You receive a structural skeleton of a Python codebase — entry points, call graph stats, top callers, and package structure. Your job is to explain what this application does, how it's organized, and what the main flows are. Write for a developer joining the team on day one. Be specific — name the actual packages, entry points, and patterns. Keep it under 500 words."""

    console.print("[dim]Asking LLM...[/]\n")

    response = provider.narrate(system=system, user=skeleton)
    console.print(response.content)
    console.print(f"\n[dim]Model: {response.model}[/]")


def _explain_flow(graph, function_name, provider, depth):
    """Explain a specific flow."""
    from cartograph.llm.narrator import narrate_flow

    target_qname = _find_function(graph, function_name)
    if not target_qname:
        console.print(f"[red]Function '{function_name}' not found[/]")
        return

    console.print(f"\n[bold blue]CARTOGRAPH[/] explaining [green]{target_qname}[/]\n")
    console.print("[dim]Narrating...[/]\n")

    response = narrate_flow(graph, target_qname, provider, depth=depth)
    console.print(response.content)
    console.print(f"\n[dim]Model: {response.model}[/]")


@main.command()
@click.argument("path", required=False, default=None)
@click.argument("function_name", required=False)
@click.option("--depth", "-d", type=int, default=5, help="Max traversal depth")
def context(path: str, function_name: str | None, depth: int):
    """Output graph context as markdown to stdout for piping to any LLM.

    \b
    Usage:
      carto context | claude "explain this codebase"
      carto context "checkout" | claude "explain this flow"
      carto context "checkout" | gh copilot explain
    """
    path, function_name = _resolve_path_and_arg(path, function_name)
    config = CartographConfig(root_path=path)
    index, graph = parse_and_build(config)

    if function_name is None:
        output = _build_codebase_context(index, graph)
    else:
        output = _build_flow_context(index, graph, function_name, depth)

    # Print raw to stdout — no Rich formatting, clean for piping
    click.echo(output)


def _build_codebase_context(index, graph) -> str:
    """Build codebase-level context as markdown."""
    from collections import Counter

    ep_by_type = Counter(ep.type.value for ep in index.entry_points)
    top_callers = sorted(
        [(qn, len(graph.get_callees(qn))) for qn in graph.functions],
        key=lambda x: -x[1],
    )[:15]

    ep_samples: dict[str, list[str]] = {}
    for ep in index.entry_points:
        t = ep.type.value
        if t not in ep_samples:
            ep_samples[t] = []
        if len(ep_samples[t]) < 8:
            ep_samples[t].append(f"{ep.trigger} → {ep.node_id.split('.')[-1]}")

    top_packages: Counter[str] = Counter()
    for mp in index.modules:
        parts = mp.split(".")
        if len(parts) >= 2:
            top_packages[parts[0] + "." + parts[1]] += 1

    # Build flow groups for richer context
    flow_groups = _group_entry_points(index, graph)

    lines = [
        "# Codebase Analysis (generated by Cartograph)\n",
        f"Modules: {len(index.modules)}",
        f"Functions: {sum(len(m.functions) for m in index.modules.values())}",
        f"Entry points: {len(index.entry_points)}",
        f"Resolved call edges: {graph.total_resolved}\n",
        "## Discovered Flows\n",
    ]

    for i, grp in enumerate(flow_groups[:20], 1):
        type_str = ", ".join(
            f"{v} {k}" for k, v in sorted(grp["types"].items(), key=lambda x: -x[1])
        )
        lines.append(
            f"### {i}. {grp['name']} ({grp['count']} entry points: {type_str})"
        )
        triggers = ", ".join(grp["triggers"])
        if grp["count"] > 3:
            triggers += f", +{grp['count'] - 3} more"
        lines.append(f"  Endpoints: {triggers}")
        if grp["deepest_reachable"] > 1:
            lines.append(
                f"  Deepest: {grp['deepest_name']} → {grp['deepest_reachable']} functions"
            )
        lines.append("")

    lines.append("## Entry Points by Type\n")
    for t, count in ep_by_type.most_common():
        lines.append(f"**{t}** ({count}):")
        for sample in ep_samples.get(t, []):
            lines.append(f"  - {sample}")
        lines.append("")

    lines.append("## Top Functions by Outgoing Calls\n")
    for qn, count in top_callers:
        lines.append(f"  {count:>3}  {qn}")

    lines.append("\n## Package Structure\n")
    for pkg, count in top_packages.most_common(15):
        lines.append(f"  {count:>3}  {pkg}")

    return "\n".join(lines)


def _build_flow_context(index, graph, function_name: str, depth: int) -> str:
    """Build flow-level context as markdown with graph + source snippets."""
    from cartograph.llm.narrator import _read_source_snippets
    from cartograph.web.serializers import serialize_graph_trace

    target_qname = _find_function(graph, function_name)
    if not target_qname:
        return f"Error: Function '{function_name}' not found."

    graph_json = serialize_graph_trace(graph, target_qname, depth)
    snippets = _read_source_snippets(graph, graph_json, max_nodes=8)

    func = graph.functions.get(target_qname)
    nodes = graph_json.get("nodes", {})
    edges = graph_json.get("edges", [])
    meta = graph_json.get("metadata", {})

    lines = [
        f"# Flow Analysis: {target_qname} (generated by Cartograph)\n",
        f"File: {func.file_path}:{func.line_start}" if func else "",
        f"Decorators: {', '.join(func.decorators)}" if func and func.decorators else "",
        f"Nodes: {meta.get('total_nodes', 0)} | "
        f"Edges: {meta.get('total_edges', 0)} | "
        f"Files: {meta.get('total_files', 0)} | "
        f"Async boundaries: {meta.get('async_boundaries', 0)}\n",
        "## Call Graph\n",
    ]

    # Edges as readable list
    for edge in edges:
        src_short = edge["source"].split(".")[-1]
        tgt_short = edge["target"].split(".")[-1]
        tgt_node = nodes.get(edge["target"], {})
        tgt_file = tgt_node.get("file", "").split("/")[-1]
        condition = (
            f" [condition: {edge.get('condition')}]" if edge.get("condition") else ""
        )
        cross = " (cross-file)" if edge.get("is_cross_file") else ""
        lines.append(f"  {src_short} → {tgt_short}{cross}{condition}  # {tgt_file}")

    # Branches on root node
    root_node = nodes.get(target_qname, {})
    branches = root_node.get("branches", [])
    if branches:
        lines.append("\n## Conditional Branches\n")
        for b in branches:
            cond = "else" if b.get("is_else") else f"if {b.get('condition', '?')}"
            calls = ", ".join(b.get("calls", [])) if b.get("calls") else "(no calls)"
            lines.append(f"  {cond} → {calls}")

    # Source code
    if snippets:
        lines.append("\n## Source Code\n")
        for qname, snippet in snippets.items():
            short = qname.split(".")[-1]
            lines.append(f"### {short} (`{qname}`)\n```python\n{snippet}\n```\n")

    return "\n".join(lines)


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--diff",
    "diff_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Path to unified diff file; defaults to `git diff HEAD` in <path>.",
)
@click.option(
    "--file",
    "files",
    multiple=True,
    help="Explicit file(s) relative to <path>. Overrides --diff.",
)
@click.option(
    "--function",
    "functions",
    multiple=True,
    help="Explicit function qname(s). Overrides --diff and --file.",
)
@click.option(
    "-d",
    "--depth",
    default=10,
    show_default=True,
    type=click.IntRange(1, 50),
)
@click.option(
    "-f",
    "--format",
    "output_format",
    type=click.Choice(["terminal", "markdown", "json"]),
    default="terminal",
    show_default=True,
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False),
    default=None,
    help="Write output to file instead of stdout.",
)
@click.option(
    "--test-dir",
    default="tests",
    show_default=True,
    help="Directory containing pytest tests relative to <path>.",
)
def blast(
    path: str,
    diff_path: str | None,
    files: tuple[str, ...],
    functions: tuple[str, ...],
    depth: int,
    output_format: str,
    output: str | None,
    test_dir: str,
) -> None:
    """Compute blast radius — show every function, entry point, and test affected by changes."""
    import sys

    from cartograph.blast.analyzer import BlastAnalyzer, UnknownQnameError
    from cartograph.blast.diff import git_diff_head, parse_changed_files
    from cartograph.blast.renderer import render_json, render_markdown, render_terminal
    from cartograph.blast.tests_index import build_test_index

    config = CartographConfig(root_path=path, include_tests=True)
    index, graph = parse_and_build(config, use_cache=True)

    # Build test index (silent skip if default test_dir missing; warn if explicit)
    test_dir_path = Path(path) / test_dir
    if test_dir_path.exists():
        test_index = build_test_index(index, test_dir_path)
    else:
        ctx = click.get_current_context()
        source = ctx.get_parameter_source("test_dir")
        if source == click.core.ParameterSource.COMMANDLINE:
            click.echo(
                f"test dir not found: {test_dir_path} (skipping test mapping)",
                err=True,
            )
        test_index = None

    analyzer = BlastAnalyzer(graph=graph, index=index, test_index=test_index)

    try:
        if functions:
            report = analyzer.analyze_functions(list(functions), max_depth=depth)
        elif files:
            changed_paths = [Path(path) / f for f in files]
            report = analyzer.analyze_files(changed_paths, max_depth=depth)
        else:
            # Default: git diff HEAD (or explicit diff file)
            if diff_path:
                diff_text = Path(diff_path).read_text(encoding="utf-8")
            else:
                try:
                    diff_text = git_diff_head(Path(path))
                except Exception as exc:
                    stderr_msg = str(exc)
                    click.echo(f"git diff failed: {stderr_msg}", err=True)
                    sys.exit(5)

            changed_paths = parse_changed_files(diff_text, Path(path))
            if not changed_paths:
                click.echo("no changes to analyze", err=True)
                sys.exit(2)
            report = analyzer.analyze_files(changed_paths, max_depth=depth)

    except UnknownQnameError as exc:
        click.echo(f"unknown function: {exc.qname}", err=True)
        sys.exit(3)

    # Check for empty result after analysis
    if (
        not report.changed_functions
        and not report.affected_functions
        and not report.changed_files
    ):
        click.echo("no changes to analyze", err=True)
        sys.exit(2)

    # Render output
    if output_format == "json":
        rendered = render_json(report)
    elif output_format == "markdown":
        rendered = render_markdown(report)
    else:
        # terminal — write to a string buffer then echo
        from io import StringIO

        from rich.console import Console as RichConsole

        if output:
            buf = StringIO()
            rich_console = RichConsole(file=buf, highlight=False)
            render_terminal(report, rich_console)
            rendered = buf.getvalue()
        else:
            render_terminal(report, console)
            rendered = None

    if rendered is not None:
        if output:
            Path(output).write_text(rendered, encoding="utf-8")
        else:
            click.echo(rendered, nl=False)


if __name__ == "__main__":
    main()
