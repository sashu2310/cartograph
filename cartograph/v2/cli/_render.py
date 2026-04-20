"""Rich renderers shared by `scan`, `entries`, `trace`, `analyze`."""

from __future__ import annotations

from pathlib import Path

from cartograph.v2.ir.analyzed import (
    AnalyzedGraph,
    ApiRouteEntry,
    CeleryTaskEntry,
    DiscoveredEntry,
    SignalHandlerEntry,
)


def pretty_scan(graph: AnalyzedGraph, project_root: Path) -> None:
    """Rich-rendered summary for `carto2 scan`. CliPresenter (deterministic
    plain text) stays available for diffing / snapshot testing."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    from cartograph.v2.stages.present.util import (
        bucket_unresolved,
        top_classes_by_usage,
    )

    console = Console()
    resolved = graph.annotated.resolved
    modules = {f.module for f in resolved.functions.values()}
    class_count = sum(1 for fn in resolved.functions.values() if fn.kind == "class")

    title = Text()
    title.append("CARTOGRAPH v2 ", style="bold magenta")
    title.append(f"— {project_root.name}", style="dim")
    console.print()
    console.print(title)
    console.print()

    stats = Table.grid(padding=(0, 2))
    stats.add_column(justify="right", style="bold cyan")
    stats.add_column()
    stats.add_row(str(len(modules)), "modules")
    stats.add_row(str(len(resolved.functions)), "functions")
    stats.add_row(str(class_count), "classes")
    stats.add_row(str(len(resolved.edges)), "edges")
    stats.add_row(str(len(resolved.unresolved)), "unresolved")
    # Per-reason breakdown so "10K unresolved" doesn't read as "broken."
    buckets = bucket_unresolved(resolved.unresolved)
    for reason in sorted(buckets, key=lambda r: -buckets[r]):
        stats.add_row(
            f"[dim]{buckets[reason]}[/]",
            f"[dim]  · {reason}[/]",
        )
    stats.add_row(str(len(graph.entry_points)), "entry points")
    console.print(Panel(stats, title="summary", expand=False))
    console.print()

    # Top classes by usage — helps orient on a new codebase (Agent, Config, etc.).
    top_classes = top_classes_by_usage(resolved, limit=8)
    if top_classes:
        console.print(Text("top classes (by usage)", style="bold dim"))
        for qn, count in top_classes:
            console.print(
                f"  [bold cyan]{count:>3}[/] [white]{qn.split('.')[-1]}[/] [dim]{qn}[/]"
            )
        console.print()

    if not graph.entry_points:
        console.print("[dim](no entry points discovered)[/]")
        return

    by_kind: dict[str, list] = {}
    for ep in graph.entry_points:
        by_kind.setdefault(ep.kind, []).append(ep)

    kind_styles = {
        "api_route": "bright_blue",
        "celery_task": "magenta",
        "celery_beat": "bright_magenta",
        "signal_handler": "yellow",
        "discovered": "green",
    }

    for kind in sorted(by_kind, key=lambda k: (-len(by_kind[k]), k)):
        entries = sorted(by_kind[kind], key=lambda e: e.qname)
        style = kind_styles.get(kind, "white")
        header = Text()
        header.append(f"{kind}", style=f"bold {style}")
        header.append(f"  ({len(entries)})", style="dim")
        console.print(header)

        # Group by top-level module for readability on large codebases.
        groups: dict[str, list] = {}
        for ep in entries:
            top = ep.qname.split(".")[0]
            groups.setdefault(top, []).append(ep)

        for top, group in sorted(groups.items(), key=lambda g: (-len(g[1]), g[0])):
            if len(groups) > 1:
                console.print(f"  [dim]{top}[/] [dim]({len(group)})[/]")
            for ep in group[:8]:
                line = pretty_entry_line(ep, style)
                prefix = "    " if len(groups) > 1 else "  "
                console.print(f"{prefix}{line}")
            if len(group) > 8:
                prefix = "    " if len(groups) > 1 else "  "
                console.print(f"{prefix}[dim]… +{len(group) - 8} more[/]")
        console.print()


def pretty_entry_line(ep, accent: str):
    """One-line rich rendering of an EntryPoint."""
    from rich.text import Text

    line = Text()
    if isinstance(ep, ApiRouteEntry):
        line.append(f"{ep.method:<6}", style=f"bold {accent}")
        line.append(f"{ep.path:<28}", style=accent)
        line.append("  → ", style="dim")
        line.append(ep.qname, style="white")
    elif isinstance(ep, CeleryTaskEntry):
        line.append(ep.qname, style="white")
        if ep.queue:
            line.append(f"  [{ep.queue}]", style=accent)
    elif isinstance(ep, SignalHandlerEntry):
        line.append(ep.qname, style="white")
        line.append(f"  {ep.signal_name}", style=accent)
        if ep.sender:
            line.append(f" ← {ep.sender}", style="dim")
    elif isinstance(ep, DiscoveredEntry):
        line.append(ep.qname, style="white")
        line.append(f"  @{ep.trigger_decorator}", style=f"dim {accent}")
    else:
        line.append(ep.qname, style="white")
    return line


def print_rich_tree(resolved, root_qname: str, *, depth: int) -> None:
    """Rich-rendered call tree rooted at `root_qname`.

    Edge-kind coloring: async dispatches pink-dashed, cross-file purple,
    conditional branches amber, sync calls gray. File:line metadata on
    the leaf of each call.
    """
    from rich.console import Console
    from rich.tree import Tree

    console = Console()
    root_ref = resolved.functions.get(root_qname)
    tree = Tree(_tree_label(root_qname, root_ref, edge=None))
    _fill_tree(resolved, root_qname, depth, tree, seen=set())
    console.print(tree)


def _fill_tree(resolved, qname: str, depth: int, node, seen: set[str]) -> None:
    if depth <= 0 or qname in seen:
        return
    seen.add(qname)
    for edge in resolved.get_callees(qname):
        callee_ref = resolved.functions.get(edge.callee_qname)
        child = node.add(_tree_label(edge.callee_qname, callee_ref, edge=edge))
        if edge.callee_qname in seen:
            child.add("[dim yellow]↻ cycle[/]")
            continue
        _fill_tree(resolved, edge.callee_qname, depth - 1, child, seen)
    seen.discard(qname)


def _tree_label(qname: str, ref, edge):
    """Rich Text label for one call-tree node; edge=None means it's the root.

    Child nodes display the *call-site* line (where in the caller the call
    happens). The root displays the callee's definition file:line. Two
    different pieces of navigation information; conflating them hides the
    one users actually want — "where is this called?" vs. "where is this
    defined?"
    """
    from rich.text import Text

    label = Text()
    if edge is not None:
        if edge.async_kind:
            label.append("⚡ ", style="bold magenta")
            label.append(edge.async_kind.replace("celery_", ""), style="magenta")
            label.append(" ", style="")
        elif edge.condition:
            label.append("? ", style="bold yellow")
            label.append(edge.condition, style="yellow")
            label.append(" ", style="")

    name = qname.split(".")[-1]
    label.append(name, style="bold white")
    label.append(f"  {qname}", style="dim")

    if edge is not None:
        # Two call sites to the same callee now render distinctly because
        # each carries its own `edge.line` from within the caller.
        label.append(f"  called@{edge.line}", style="dim yellow")
        if ref is not None:
            label.append(
                f"  def→{ref.source_path.name}:{ref.line_start}", style="dim cyan"
            )
    elif ref is not None:
        label.append(f"  {ref.source_path.name}:{ref.line_start}", style="dim cyan")
    return label


def pretty_analysis(report, limit: int = 20) -> None:
    """Rich-rendered analysis report with one table per finding kind."""
    from rich.console import Console
    from rich.table import Table

    console = Console()

    # N+1 candidates
    if report.n_plus_one:
        t = Table(
            title="N+1 ORM candidates (same model read ≥2 times in one function)",
            title_style="bold red",
            header_style="bold",
        )
        t.add_column("reads", justify="right", style="red")
        t.add_column("model", style="cyan")
        t.add_column("function")
        t.add_column("lines", style="dim")
        for c in report.n_plus_one:
            t.add_row(str(c.read_count), c.model, c.qname, ", ".join(map(str, c.lines)))
        console.print(t)
        console.print()
    else:
        console.print("[green]✓ no N+1 ORM candidates[/]\n")

    # Model hotspots
    if report.hotspots:
        t = Table(
            title="Model hotspots",
            title_style="bold cyan",
            header_style="bold",
        )
        t.add_column("model", style="cyan")
        t.add_column("total", justify="right", style="bold")
        t.add_column("R", justify="right", style="green")
        t.add_column("W", justify="right", style="yellow")
        t.add_column("D", justify="right", style="red")
        t.add_column("functions", justify="right", style="dim")
        for h in report.hotspots[:limit]:
            t.add_row(
                h.model,
                str(h.total),
                str(h.reads),
                str(h.writes),
                str(h.deletes),
                str(h.accessing_functions),
            )
        console.print(t)
        if len(report.hotspots) > limit:
            console.print(f"[dim]… +{len(report.hotspots) - 15} more models[/]")
        console.print()

    # Mixed operations
    if report.mixed_ops:
        t = Table(
            title="Mixed-operation functions (>1 distinct read/write/delete)",
            title_style="bold yellow",
            header_style="bold",
        )
        t.add_column("ops", style="yellow")
        t.add_column("function")
        t.add_column("models", style="dim")
        for m in report.mixed_ops[:limit]:
            t.add_row("+".join(m.operations), m.qname, ", ".join(m.models))
        console.print(t)
        if len(report.mixed_ops) > limit:
            console.print(f"[dim]… +{len(report.mixed_ops) - 20} more[/]")
        console.print()

    # Async boundary crossings
    if report.boundary_crossings:
        t = Table(
            title="Async-boundary crossings (DB + async dispatch in same body)",
            title_style="bold magenta",
            header_style="bold",
        )
        t.add_column("orm", justify="right", style="green")
        t.add_column("dispatch", justify="right", style="magenta")
        t.add_column("kind", style="magenta")
        t.add_column("function")
        t.add_column("models", style="dim")
        for b in report.boundary_crossings[:limit]:
            t.add_row(
                str(b.orm_count),
                str(b.async_dispatch_count),
                "+".join(b.dispatches),
                b.qname,
                ", ".join(b.models),
            )
        console.print(t)
        if len(report.boundary_crossings) > limit:
            console.print(f"[dim]… +{len(report.boundary_crossings) - 20} more[/]")
        console.print()

    # Long call chains (entry point reaches deep into the callee tree)
    if report.long_call_chains:
        t = Table(
            title=f"Long call chains ({len(report.long_call_chains)})",
            title_style="bold yellow",
            header_style="bold",
        )
        t.add_column("entry", style="white")
        t.add_column("depth", justify="right", style="bold yellow")
        t.add_column("deepest reachable", style="dim")
        for c in report.long_call_chains[:limit]:
            t.add_row(c.entry_qname, str(c.depth), c.deepest_callee)
        console.print(t)
        if len(report.long_call_chains) > limit:
            console.print(
                f"[dim]… +{len(report.long_call_chains) - 15} more chains[/]"
            )
        console.print()

    # Path collisions (FastAPI/Flask/Ninja routes sharing method+path)
    if report.path_collisions:
        t = Table(
            title=f"Path collisions ({len(report.path_collisions)})",
            title_style="bold red",
            header_style="bold",
        )
        t.add_column("method", style="bold")
        t.add_column("path", style="cyan")
        t.add_column("handlers", style="dim")
        for c in report.path_collisions[:limit]:
            t.add_row(c.method, c.path, "\n".join(c.handlers))
        console.print(t)
        if len(report.path_collisions) > limit:
            console.print(
                f"[dim]… +{len(report.path_collisions) - 20} more collisions[/]"
            )
        console.print()

    # Sync-in-async (framework-agnostic; curated blocking-symbol table)
    if report.sync_in_async:
        t = Table(
            title=f"Sync-in-async ({len(report.sync_in_async)})",
            title_style="bold magenta",
            header_style="bold",
        )
        t.add_column("async function", style="white")
        t.add_column("blocking call", style="magenta")
        t.add_column("line", justify="right", style="dim")
        for s in report.sync_in_async[:limit]:
            t.add_row(s.async_qname, s.blocking_call, str(s.line))
        console.print(t)
        if len(report.sync_in_async) > limit:
            console.print(
                f"[dim]… +{len(report.sync_in_async) - 20} more findings[/]"
            )
        console.print()

    # Import cycles (framework-agnostic; fires on any project)
    if report.import_cycles:
        t = Table(
            title=f"Import cycles ({len(report.import_cycles)})",
            title_style="bold red",
            header_style="bold",
        )
        t.add_column("#", justify="right", style="dim")
        t.add_column("cycle", style="white")
        for i, cycle in enumerate(report.import_cycles[:limit], 1):
            t.add_row(str(i), " → ".join(cycle.modules) + " → " + cycle.modules[0])
        console.print(t)
        if len(report.import_cycles) > limit:
            console.print(
                f"[dim]… +{len(report.import_cycles) - 20} more cycles[/]"
            )
        console.print()

    if not (
        report.n_plus_one
        or report.hotspots
        or report.mixed_ops
        or report.boundary_crossings
        or report.import_cycles
        or report.sync_in_async
        or report.path_collisions
        or report.long_call_chains
    ):
        console.print(
            "[dim](no findings — either no ORM/async patterns, "
            "no import cycles, or nothing is suspicious)[/]"
        )
