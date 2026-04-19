"""carto2 — harnessing deterministic context for LLMs."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from cartograph.v2.config import RunConfig
from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.base import is_err
from cartograph.v2.pipeline import Pipeline
from cartograph.v2.stages.annotate.registry import default_annotators
from cartograph.v2.stages.discover.topology import TopologyDiscoverer
from cartograph.v2.stages.extract.treesitter_extractor import TreesitterExtractor
from cartograph.v2.stages.present.cli import CliPresenter
from cartograph.v2.stages.present.llm import LlmPresenter
from cartograph.v2.stages.present.markdown import codebase_markdown, flow_markdown
from cartograph.v2.stages.present.web import serve as serve_web
from cartograph.v2.stages.resolve.lsp.server import LspServer
from cartograph.v2.stages.resolve.ty_resolver import TyResolver

_LAST_PROJECT_FILE = Path.home() / ".cartograph" / "last_project_v2"


def _resolve_qname(functions: dict, name: str) -> str | None:
    """Map a user-supplied name to a full qname: exact → suffix → substring.

    Matches v1's `_find_function` behaviour. First suffix hit and first
    substring hit win — no scoring, no ranking. Callers get `None` if
    nothing matches; _qname_suggestions() supplies hints for the error.
    """
    if name in functions:
        return name
    for qn in functions:
        if qn.endswith(f".{name}"):
            return qn
    needle = name.lower()
    for qn in functions:
        if needle in qn.lower():
            return qn
    return None


def _qname_suggestions(functions: dict, name: str, n: int = 5) -> list[str]:
    """Top-n substring-matching qnames, for 'did you mean' messages."""
    needle = name.lower()
    return [qn for qn in functions if needle in qn.lower()][:n]


def _require_qname(functions: dict, name: str) -> str:
    """Resolve or raise ClickException with suggestions."""
    resolved = _resolve_qname(functions, name)
    if resolved is not None:
        return resolved
    hints = _qname_suggestions(functions, name)
    hint_block = "\n  ".join(hints) if hints else "(no similar names found)"
    raise click.ClickException(f"unknown qname: {name}\ndid you mean:\n  {hint_block}")


def _save_last_project(path: Path) -> None:
    _LAST_PROJECT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LAST_PROJECT_FILE.write_text(str(path.resolve()))


def _get_last_project() -> Path | None:
    if not _LAST_PROJECT_FILE.exists():
        return None
    candidate = Path(_LAST_PROJECT_FILE.read_text().strip())
    return candidate if candidate.exists() else None


def _resolve_path(path: Path | None) -> Path:
    """Use the given path if provided; otherwise fall back to the last `init`-ed project."""
    if path is not None:
        return path.resolve()
    last = _get_last_project()
    if last is None:
        raise click.ClickException(
            "no project path given and no previous `init` found. "
            "run: carto2 init /path/to/project"
        )
    click.echo(f"(using last project: {last})", err=True)
    return last


def _build_pipeline(server: LspServer) -> Pipeline:
    return Pipeline(
        extractor=TreesitterExtractor(),
        resolver=TyResolver(server=server),
        annotators=default_annotators(),
        discoverer=TopologyDiscoverer(),
        presenter=CliPresenter(),
    )


async def _build_graph(path: Path, include_tests: bool) -> AnalyzedGraph:
    import time
    from typing import Any

    stats: dict[str, Any] = {}
    start = time.perf_counter()
    async with LspServer(["ty", "server"]) as server:
        pipeline = _build_pipeline(server)
        result = await pipeline.build(
            RunConfig(project_root=path, include_tests=include_tests),
            stats=stats,
        )
    elapsed = time.perf_counter() - start
    if is_err(result):
        raise click.ClickException(f"pipeline failed: {result.error}")
    _print_cache_footer(stats, elapsed)
    # is_err narrowed the union above; ty's TypeGuard inference is imperfect
    # here, so explicit assert + attribute access preserves correctness.
    assert not is_err(result)
    return result.value


def _print_cache_footer(stats: dict, elapsed: float) -> None:
    """Single-line cache + timing summary on stderr.

    Format: `(2.4s · resolve: hit · extract: 42/42 hit)`
    On stderr so it never contaminates pipes like `carto2 context | claude`.
    """
    parts = [f"{elapsed:.2f}s"]
    resolve_hit = stats.get("resolve_cache_hit")
    if resolve_hit is True:
        parts.append("[green]resolve: hit[/]")
    elif resolve_hit is False:
        parts.append("[yellow]resolve: miss[/]")
    extract_hits = stats.get("extract_hits", 0) or 0
    extract_misses = stats.get("extract_misses", 0) or 0
    total = extract_hits + extract_misses
    if total > 0:
        parts.append(f"extract: {extract_hits}/{total} hit")
    from rich.console import Console

    Console(stderr=True).print(f"[dim]({' · '.join(parts)})[/]")


def _verbose_callback(_ctx, _param, value):
    """Reconfigure logfire to emit INFO spans when `-v/--verbose` is set.

    logfire is configured at import time (see cartograph/v2/__init__.py) —
    running it again here with a lower min-log-level replaces the sink
    before any command starts, so stage-timing spans print inline.
    """
    if value:
        import logfire

        logfire.configure(
            send_to_logfire=False,
            service_name="cartograph-v2",
            console=logfire.ConsoleOptions(min_log_level="info"),
        )
    return value


@click.group()
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    expose_value=False,
    is_eager=True,
    callback=_verbose_callback,
    help="Stream stage-timing spans (extract, resolve, annotate, discover) to stderr.",
)
def main() -> None:
    """Cartograph v2 — harnessing deterministic context for LLMs."""


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--include-tests/--no-tests", default=False, show_default=True)
def init(path: Path, include_tests: bool) -> None:
    """Scan a project and remember its path for later commands."""
    graph = asyncio.run(_build_graph(path, include_tests))
    _save_last_project(path)
    _pretty_scan(graph, path)
    click.echo(f"\n(saved as last project: {path.resolve()})", err=True)


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--include-tests/--no-tests", default=False, show_default=True)
def scan(path: Path | None, include_tests: bool) -> None:
    """Scan a project and print a summary."""
    resolved_path = _resolve_path(path)
    graph = asyncio.run(_build_graph(resolved_path, include_tests))
    _pretty_scan(graph, resolved_path)


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--kind", default=None, help="filter by entry-point kind")
def entries(path: Path | None, kind: str | None) -> None:
    """List discovered entry points (rich-rendered; same shape as `carto2 scan`)."""
    from rich.console import Console

    resolved_path = _resolve_path(path)
    graph = asyncio.run(_build_graph(resolved_path, include_tests=False))

    kind_styles = {
        "api_route": "bright_blue",
        "celery_task": "magenta",
        "celery_beat": "bright_magenta",
        "signal_handler": "yellow",
        "discovered": "green",
    }

    console = Console()
    hits = [ep for ep in graph.entry_points if kind is None or ep.kind == kind]
    if not hits:
        console.print("[dim](no entry points match)[/]")
        return
    for ep in sorted(hits, key=lambda e: (e.kind, e.qname)):
        accent = kind_styles.get(ep.kind, "white")
        console.print(_pretty_entry_line(ep, accent))


@main.command()
@click.argument("qname")
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--depth", default=5, type=int, show_default=True)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the trace as JSON to this file instead of printing a tree.",
)
def trace(qname: str, path: Path | None, depth: int, output: Path | None) -> None:
    """Walk the call tree rooted at QNAME.

    Prints an indented tree to stdout by default. With `-o PATH`, writes a
    JSON document (nodes + edges + metadata — same shape the web viewer
    consumes) suitable for piping into other tools.
    """
    import json as _json

    from cartograph.v2.stages.present.web_serializers import serialize_graph_trace

    resolved_path = _resolve_path(path)
    graph = asyncio.run(_build_graph(resolved_path, include_tests=False))
    resolved = graph.annotated.resolved
    qname = _require_qname(resolved.functions, qname)
    if output is not None:
        payload = serialize_graph_trace(graph, qname, depth)
        output.write_text(_json.dumps(payload, indent=2))
        click.echo(f"wrote {output} ({len(payload['edges'])} edges)", err=True)
        return
    _print_rich_tree(resolved, qname, depth=depth)


@main.command()
@click.argument("qname")
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
def callers(qname: str, path: Path | None) -> None:
    """Reverse lookup: list functions that call QNAME."""
    resolved_path = _resolve_path(path)
    graph = asyncio.run(_build_graph(resolved_path, include_tests=False))
    resolved = graph.annotated.resolved
    qname = _require_qname(resolved.functions, qname)
    edges = resolved.get_callers(qname)
    if not edges:
        click.echo(f"(no callers found for {qname})")
        return
    for e in edges:
        click.echo(f"{e.caller_qname}  (line {e.line})")


@main.command()
@click.argument("query")
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--limit", default=20, type=int, show_default=True)
def search(query: str, path: Path | None, limit: int) -> None:
    """Find functions by name, ranked by function-name match first.

    Function-name hits are scored above module-path hits, so `search Agent`
    returns `pydantic_ai.Agent` before `weather_agent_gradio.stream_from_agent`.
    """
    from rich.console import Console

    from cartograph.v2.stages.present.cli import ranked_search

    resolved_path = _resolve_path(path)
    graph = asyncio.run(_build_graph(resolved_path, include_tests=False))
    resolved = graph.annotated.resolved

    hits = ranked_search(resolved, query, limit)
    if not hits:
        click.echo(f"(no matches for {query!r})")
        return
    console = Console()
    for _, qname in hits:
        fn = resolved.functions[qname]
        name = qname.rsplit(".", 1)[-1]
        kind_tag = f"[dim yellow]{fn.kind}[/]" if fn.kind != "function" else ""
        console.print(
            f"[bold white]{name}[/]  [dim]{qname}[/]  {kind_tag}  "
            f"[dim cyan]{fn.source_path.name}:{fn.line_start}[/]"
        )


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=3333, type=int, show_default=True)
def serve(path: Path | None, host: str, port: int) -> None:
    """Run the interactive web viewer."""
    resolved_path = _resolve_path(path)
    graph = asyncio.run(_build_graph(resolved_path, include_tests=False))
    serve_web(graph, host=host, port=port, project_name=resolved_path.name)


@main.command()
@click.argument("qname")
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--depth", default=4, type=int, show_default=True)
@click.option("--model", default=None, help="pydantic-ai model string")
def explain(qname: str, path: Path | None, depth: int, model: str | None) -> None:
    """LLM-narrate the flow rooted at QNAME (pydantic-ai → Claude direct)."""
    resolved_path = _resolve_path(path)
    graph = asyncio.run(_build_graph(resolved_path, include_tests=False))
    qname = _require_qname(graph.annotated.resolved.functions, qname)
    options: dict = {"entry_qname": qname, "depth": depth}
    if model:
        options["model"] = model
    click.echo(LlmPresenter().render(graph, options).decode())


@main.command()
@click.argument("qname", required=False)
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--depth", default=5, type=int, show_default=True)
@click.option(
    "--answer",
    default=None,
    help='Question-scoped markdown. Examples: "what calls X", "callers of X", "what does X call", "flow of X".',
)
@click.option(
    "--max-tokens",
    default=None,
    type=int,
    help="Cap the flow-context output at ~N tokens (greedy BFS; chars/4 approximation).",
)
def context(
    qname: str | None,
    path: Path | None,
    depth: int,
    answer: str | None,
    max_tokens: int | None,
) -> None:
    """Emit graph-as-markdown for piping to external LLMs.

    \b
    Usage:
      carto2 context | claude "explain this codebase"
      carto2 context checkout | claude "explain this flow"
      carto2 context --answer "what calls checkout" | claude
      carto2 context checkout --max-tokens 2000 | claude
    """
    from cartograph.v2.stages.present.markdown import (
        callees_markdown,
        callers_markdown,
        parse_answer_question,
    )

    # context has two optional positional args; users often pass ONLY a path
    # (e.g. `carto2 context /tmp/fastapi`). Detect that and re-bind so the
    # arg becomes `path`, not `qname`.
    if qname is not None and path is None and Path(qname).exists():
        path = Path(qname)
        qname = None

    resolved_path = _resolve_path(path)
    graph = asyncio.run(_build_graph(resolved_path, include_tests=False))

    if answer is not None:
        parsed = parse_answer_question(answer)
        if parsed is None:
            raise click.ClickException(
                f"couldn't parse question: {answer!r}. Try: "
                '"what calls X", "what does X call", "flow of X".'
            )
        kind, target = parsed
        resolved_qname = _require_qname(graph.annotated.resolved.functions, target)
        if kind == "callers":
            click.echo(callers_markdown(graph, resolved_qname))
        elif kind == "callees":
            click.echo(callees_markdown(graph, resolved_qname))
        else:  # flow
            click.echo(
                flow_markdown(graph, resolved_qname, depth, max_tokens=max_tokens)
            )
        return

    if qname is None:
        click.echo(codebase_markdown(graph))
    else:
        qname = _require_qname(graph.annotated.resolved.functions, qname)
        click.echo(flow_markdown(graph, qname, depth, max_tokens=max_tokens))


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the full report as JSON to this file instead of printing tables.",
)
def analyze(path: Path | None, output: Path | None) -> None:
    """Engineering-insight analyses over the graph.

    Reports N+1 ORM candidates, model hotspots, mixed-operation functions,
    and async-boundary crossings (functions touching DB + async dispatch).
    """

    from cartograph.v2.analyses import analyze as run_analyses

    resolved_path = _resolve_path(path)
    graph = asyncio.run(_build_graph(resolved_path, include_tests=False))
    report = run_analyses(graph)

    if output is not None:
        output.write_text(report.model_dump_json(indent=2))
        click.echo(f"wrote {output}", err=True)
        return

    _pretty_analysis(report)


def _pretty_analysis(report) -> None:
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
        for h in report.hotspots[:15]:
            t.add_row(
                h.model,
                str(h.total),
                str(h.reads),
                str(h.writes),
                str(h.deletes),
                str(h.accessing_functions),
            )
        console.print(t)
        if len(report.hotspots) > 15:
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
        for m in report.mixed_ops[:20]:
            t.add_row("+".join(m.operations), m.qname, ", ".join(m.models))
        console.print(t)
        if len(report.mixed_ops) > 20:
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
        for b in report.boundary_crossings[:20]:
            t.add_row(
                str(b.orm_count),
                str(b.async_dispatch_count),
                "+".join(b.dispatches),
                b.qname,
                ", ".join(b.models),
            )
        console.print(t)
        if len(report.boundary_crossings) > 20:
            console.print(f"[dim]… +{len(report.boundary_crossings) - 20} more[/]")
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
        for s in report.sync_in_async[:20]:
            t.add_row(s.async_qname, s.blocking_call, str(s.line))
        console.print(t)
        if len(report.sync_in_async) > 20:
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
        for i, cycle in enumerate(report.import_cycles[:20], 1):
            t.add_row(str(i), " → ".join(cycle.modules) + " → " + cycle.modules[0])
        console.print(t)
        if len(report.import_cycles) > 20:
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
    ):
        console.print(
            "[dim](no findings — either no ORM/async patterns, "
            "no import cycles, or nothing is suspicious)[/]"
        )


@main.command()
@click.option(
    "--rename",
    required=True,
    help="Format: `old.qname:new_name`. Example: `pydantic_ai.Agent:Assistant`",
)
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the impact report as JSON to this file.",
)
def impact(path: Path | None, rename: str, output: Path | None) -> None:
    """Report every call site that would break under a symbol rename.

    Read-only — emits a plan, never modifies files. Imports are not yet
    enumerated (ImportStmt doesn't carry line numbers in the IR); the
    footer notes this so users can grep for lingering references.
    """

    from rich.console import Console
    from rich.table import Table

    from cartograph.v2.analyses import rename_impact

    if ":" not in rename:
        raise click.ClickException("expected --rename in the form `old.qname:new_name`")
    old_qname, new_name = rename.split(":", 1)
    if not new_name:
        raise click.ClickException("new name cannot be empty")

    resolved_path = _resolve_path(path)
    graph = asyncio.run(_build_graph(resolved_path, include_tests=False))
    resolved_old = _require_qname(graph.annotated.resolved.functions, old_qname)

    report = rename_impact(graph, resolved_old, new_name)

    if output is not None:
        output.write_text(report.model_dump_json(indent=2))
        click.echo(f"wrote {output} ({len(report.call_sites)} call sites)", err=True)
        return

    console = Console()
    console.print(
        f"[bold]rename[/]  [red]{report.old_qname}[/] → [green]{report.new_name}[/]\n"
    )
    console.print(
        f"[dim]definition:[/] {Path(report.definition_file).name}:{report.definition_line}"
    )
    console.print()

    if not report.call_sites:
        console.print("[dim](no call sites found — rename affects definition only)[/]")
    else:
        t = Table(
            title=f"call sites ({len(report.call_sites)})",
            title_style="bold red",
            header_style="bold",
        )
        t.add_column("file:line", style="dim cyan")
        t.add_column("caller", style="dim")
        for s in report.call_sites:
            fname = Path(s.file).name
            t.add_row(f"{fname}:{s.line}", s.caller_qname)
        console.print(t)
        console.print()

    if report.import_sites:
        t = Table(
            title=f"import sites ({len(report.import_sites)})",
            title_style="bold yellow",
            header_style="bold",
        )
        t.add_column("file:line", style="dim cyan")
        t.add_column("statement", style="dim")
        for s in report.import_sites:
            fname = Path(s.file).name
            t.add_row(f"{fname}:{s.line}", s.statement)
        console.print(t)
        console.print()
    else:
        console.print("[dim](no import statements reference this name)[/]")


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write findings as JSON to this file instead of printing a table.",
)
def dead(path: Path | None, output: Path | None) -> None:
    """Report functions and classes with zero incoming edges and no entry-point
    status — candidates for deletion, pending review for dynamic dispatch.

    Heuristic. May flag library-intended exports or code reached via getattr /
    __getattr__ / string-indexed callable maps. Treat as a starting list."""
    import json as _json

    from rich.console import Console
    from rich.table import Table

    from cartograph.v2.analyses import find_dead

    resolved_path = _resolve_path(path)
    graph = asyncio.run(_build_graph(resolved_path, include_tests=False))
    findings = list(find_dead(graph))

    if output is not None:
        payload = [f.model_dump() for f in findings]
        output.write_text(_json.dumps(payload, indent=2))
        click.echo(f"wrote {output} ({len(findings)} dead)", err=True)
        return

    if not findings:
        click.echo("[no dead code found]")
        return

    console = Console()
    # Group by kind for readability — classes and methods cluster separately
    # from top-level functions.
    by_kind: dict[str, list] = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)

    for kind in ("function", "method", "class"):
        rows = sorted(by_kind.get(kind, []), key=lambda f: f.qname)
        if not rows:
            continue
        t = Table(
            title=f"dead {kind}s ({len(rows)})",
            title_style="bold red",
            header_style="bold",
        )
        t.add_column("qname", style="dim")
        t.add_column("location", style="dim cyan")
        for f in rows[:50]:
            fname = Path(f.source_path).name
            t.add_row(f.qname, f"{fname}:{f.line_start}")
        console.print(t)
        if len(rows) > 50:
            plural = "classes" if kind == "class" else f"{kind}s"
            console.print(f"[dim]… +{len(rows) - 50} more {plural}[/]")
        console.print()

    console.print(
        "[dim]Heuristic: dynamic dispatch (getattr, __getattr__, "
        "string-indexed callables) can bypass the static graph. "
        "Review before deleting.[/]"
    )


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
def mcp(path: Path | None) -> None:
    """Run an MCP server (stdio) exposing the pipeline to agent hosts.

    Point Claude Code at this with:
      claude mcp add cartograph -- carto2 mcp /path/to/project
    """
    from cartograph.v2.mcp.server import serve as serve_mcp

    resolved = _resolve_path(path)
    serve_mcp(resolved)


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option(
    "--targets",
    default="v1,v2-ty",
    help="comma-separated producer list",
    show_default=True,
)
def benchmark(path: Path | None, targets: str) -> None:
    """Run triangulation on a project: v1 ↔ v2-ty."""
    from cartograph.v2.benchmark.metrics import compare
    from cartograph.v2.benchmark.runner import run_target

    resolved_path = _resolve_path(path)

    async def _collect():
        out = {}
        for name in (t.strip() for t in targets.split(",")):
            click.echo(f"running {name} …", err=True)
            out[name] = await run_target(
                name, resolved_path, project_name=resolved_path.name
            )
        return out

    results = asyncio.run(_collect())
    names = list(results)

    click.echo("")
    click.echo(f"{'producer':<14} {'time(s)':>8} {'edges':>7} {'entries':>8}")
    click.echo("─" * 42)
    for n in names:
        r = results[n]
        click.echo(
            f"{r.target:<14} {r.wall_time_s:>8.2f} "
            f"{len(r.graph.edges):>7} {len(r.graph.entry_points):>8}"
        )

    if len(names) >= 2:
        click.echo("")
        click.echo("Pairwise overlap:")
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                r = compare(results[names[i]], results[names[j]])
                click.echo(
                    f"  {r.a.target} ↔ {r.b.target}: "
                    f"jaccard={r.jaccard:.3f}  "
                    f"shared={r.shared_edges}  "
                    f"only-{r.a.target}={r.only_a}  "
                    f"only-{r.b.target}={r.only_b}"
                )


def _pretty_scan(graph: AnalyzedGraph, project_root: Path) -> None:
    """Rich-rendered summary for `carto2 scan`. CliPresenter (deterministic
    plain text) stays available for diffing / snapshot testing."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    from cartograph.v2.stages.present.cli import (
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
                line = _pretty_entry_line(ep, style)
                prefix = "    " if len(groups) > 1 else "  "
                console.print(f"{prefix}{line}")
            if len(group) > 8:
                prefix = "    " if len(groups) > 1 else "  "
                console.print(f"{prefix}[dim]… +{len(group) - 8} more[/]")
        console.print()


def _pretty_entry_line(ep, accent: str):
    """One-line rich rendering of an EntryPoint."""
    from rich.text import Text

    from cartograph.v2.ir.analyzed import (
        ApiRouteEntry,
        CeleryTaskEntry,
        DiscoveredEntry,
        SignalHandlerEntry,
    )

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


def _print_rich_tree(resolved, root_qname: str, *, depth: int) -> None:
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


if __name__ == "__main__":
    main()
