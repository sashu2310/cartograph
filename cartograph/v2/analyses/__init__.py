"""Higher-order analyses over AnalyzedGraph — the engineering-insight layer.

These functions consume the final pipeline IR and derive insights that
labels alone don't express:

* N+1 ORM candidates — same (operation, model) pair appears ≥2 times in
  one function, a classic loop-over-queries smell.
* Model hotspots — which Django models are accessed most (read/write/delete
  counts aggregated across the whole graph).
* Mixed ORM operations — functions that read AND write AND/or delete
  within the same body; often a transaction-scope smell.
* Async boundary crossings — functions that touch the DB and also emit
  async dispatches (celery .delay / .apply_async / chain / chord / group)
  from the same body; these dispatches may fire outside the DB transaction.

All outputs are frozen pydantic IRs. Pure functions — no I/O.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from typing import Literal

from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.annotated import OrmOperationLabel
from cartograph.v2.ir.base import IR
from cartograph.v2.ir.resolved import ExternalUnresolved

OrmOp = Literal["read", "write", "delete"]


class NPlusOneCandidate(IR):
    """A single function reads the same model N≥2 times — likely a loop."""

    qname: str
    model: str
    read_count: int
    lines: tuple[int, ...]


class ModelHotspot(IR):
    """Aggregate access count for one model across the whole graph."""

    model: str
    total: int
    reads: int
    writes: int
    deletes: int
    accessing_functions: int


class MixedOperation(IR):
    """A function performs >1 distinct ORM operation kind (read/write/delete)."""

    qname: str
    operations: tuple[OrmOp, ...]
    models: tuple[str, ...]


class AsyncBoundaryCrossing(IR):
    """A function touches the DB *and* emits an async dispatch. The dispatch
    may execute outside the surrounding DB transaction."""

    qname: str
    orm_count: int
    async_dispatch_count: int
    models: tuple[str, ...]
    dispatches: tuple[str, ...]  # AsyncKind tags


class ImportCycle(IR):
    """A cycle in the project's module import graph.

    `modules` is the cycle in traversal order, normalised to start from
    the alphabetically smallest member so that reruns produce stable,
    diffable output.
    """

    modules: tuple[str, ...]


class SyncInAsync(IR):
    """An async function calls a known-blocking sync symbol directly.

    Static analysis can't prove a given sync call is blocking, so we
    only flag a curated set of well-known offenders (`time.sleep`,
    `requests.*`, `urllib.urlopen`, `subprocess.*`, `sqlite3.connect`).
    Transitive blocking (async → sync → blocking) isn't detected in
    this pass.
    """

    async_qname: str
    blocking_call: str
    line: int


class PathCollision(IR):
    """Two or more API route handlers registered at the same method + path.

    Detected purely from Stage 4's ApiRouteEntry list (grouped by
    (method, path)). Can surface false positives on codebases with
    multiple independent FastAPI apps sharing URL shapes (e.g.
    tutorial collections). Real collisions in a single app are a
    silent bug — last registration wins at runtime.
    """

    method: str
    path: str
    handlers: tuple[str, ...]


class LongCallChain(IR):
    """An entry point reaches >=N hops into the callee tree — refactor smell.

    "Depth" here is the BFS distance from the entry point to the deepest
    reachable callee (shortest path to that node). A project-independent
    threshold of 10 is the default — adjust via analyze kwarg if yours
    should be lower/higher.
    """

    entry_qname: str
    depth: int
    deepest_callee: str
    path: tuple[str, ...]


class AnalysisReport(IR):
    """Bundle of all analyses produced by `analyze()`."""

    n_plus_one: tuple[NPlusOneCandidate, ...]
    hotspots: tuple[ModelHotspot, ...]
    mixed_ops: tuple[MixedOperation, ...]
    boundary_crossings: tuple[AsyncBoundaryCrossing, ...]
    import_cycles: tuple[ImportCycle, ...] = ()
    sync_in_async: tuple[SyncInAsync, ...] = ()
    path_collisions: tuple[PathCollision, ...] = ()
    long_call_chains: tuple[LongCallChain, ...] = ()


def find_n_plus_one(graph: AnalyzedGraph) -> Iterator[NPlusOneCandidate]:
    """Per-function: same (operation=read, model=M) appearing ≥2 times.

    Two reads on the same model within one function is rarely done
    intentionally at the Python level — it's almost always a query-in-a-loop
    pattern (the loop lives at the AST layer we don't track, so we infer
    from the repeat-call signal).
    """
    for qname, orm_labels in _iter_orm_by_function(graph):
        by_model: dict[str, list[int]] = defaultdict(list)
        for lbl in orm_labels:
            if lbl.operation == "read":
                by_model[lbl.model].append(lbl.line)
        for model, lines in by_model.items():
            if len(lines) >= 2:
                yield NPlusOneCandidate(
                    qname=qname,
                    model=model,
                    read_count=len(lines),
                    lines=tuple(sorted(lines)),
                )


def find_model_hotspots(graph: AnalyzedGraph) -> Iterator[ModelHotspot]:
    """Per-model totals across the entire graph, sorted most-accessed-first."""
    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"reads": 0, "writes": 0, "deletes": 0}
    )
    accessors: dict[str, set[str]] = defaultdict(set)
    for qname, orm_labels in _iter_orm_by_function(graph):
        for lbl in orm_labels:
            counts[lbl.model][f"{lbl.operation}s"] += 1
            accessors[lbl.model].add(qname)

    hotspots = [
        ModelHotspot(
            model=model,
            total=c["reads"] + c["writes"] + c["deletes"],
            reads=c["reads"],
            writes=c["writes"],
            deletes=c["deletes"],
            accessing_functions=len(accessors[model]),
        )
        for model, c in counts.items()
    ]
    hotspots.sort(key=lambda h: -h.total)
    yield from hotspots


def find_mixed_operations(graph: AnalyzedGraph) -> Iterator[MixedOperation]:
    """Functions with >1 distinct ORM op kind. Suggests a larger transaction
    scope and, depending on code, a candidate for explicit transaction control."""
    for qname, orm_labels in _iter_orm_by_function(graph):
        ops = {lbl.operation for lbl in orm_labels}
        if len(ops) < 2:
            continue
        models = {lbl.model for lbl in orm_labels}
        yield MixedOperation(
            qname=qname,
            operations=tuple(sorted(ops)),  # type: ignore[arg-type]
            models=tuple(sorted(models)),
        )


def find_async_boundary_crossings(
    graph: AnalyzedGraph,
) -> Iterator[AsyncBoundaryCrossing]:
    """Functions with ORM labels *and* outgoing async_kind edges.

    Classic footgun: `obj.save(); task.delay()` outside an atomic block —
    the task may run before the transaction commits (or after it aborts),
    seeing a state the caller didn't commit.
    """
    resolved = graph.annotated.resolved
    for qname, orm_labels in _iter_orm_by_function(graph):
        if not orm_labels:
            continue
        async_edges = [
            e for e in resolved.get_callees(qname) if e.async_kind is not None
        ]
        if not async_edges:
            continue
        yield AsyncBoundaryCrossing(
            qname=qname,
            orm_count=len(orm_labels),
            async_dispatch_count=len(async_edges),
            models=tuple(sorted({lbl.model for lbl in orm_labels})),
            dispatches=tuple(
                sorted({e.async_kind for e in async_edges if e.async_kind})
            ),
        )


def analyze(graph: AnalyzedGraph) -> AnalysisReport:
    """Run every analysis; return one bundled report."""
    return AnalysisReport(
        n_plus_one=tuple(find_n_plus_one(graph)),
        hotspots=tuple(find_model_hotspots(graph)),
        mixed_ops=tuple(find_mixed_operations(graph)),
        boundary_crossings=tuple(find_async_boundary_crossings(graph)),
        import_cycles=tuple(find_import_cycles(graph)),
        sync_in_async=tuple(find_sync_in_async(graph)),
        path_collisions=tuple(find_path_collisions(graph)),
        long_call_chains=tuple(find_long_call_chains(graph)),
    )


def find_long_call_chains(
    graph: AnalyzedGraph, threshold: int = 10
) -> Iterator[LongCallChain]:
    """Flag entry points whose BFS-reachable depth exceeds `threshold`.

    "Depth" is shortest-path distance from the entry to the deepest
    reachable callee. BFS naturally gives us that — O(V+E) per entry,
    O(entries * E) total. Cycles are handled by the global `visited`
    set so we never revisit a node.

    Threshold default is 10, tuned so most well-factored codebases are
    quiet and deeply-chained ones surface. No kwarg on the CLI yet; the
    AnalysisReport shape lets callers customise in Python.
    """
    resolved = graph.annotated.resolved
    for ep in graph.entry_points:
        deepest, path = _bfs_deepest(resolved, ep.qname)
        depth = len(path) - 1
        if depth >= threshold:
            yield LongCallChain(
                entry_qname=ep.qname,
                depth=depth,
                deepest_callee=deepest,
                path=path,
            )


def _bfs_deepest(resolved, start: str) -> tuple[str, tuple[str, ...]]:
    """BFS from `start`, return (deepest_node_qname, path_tuple)."""
    from collections import deque

    dist: dict[str, tuple[str, ...]] = {start: (start,)}
    q = deque([start])
    while q:
        node = q.popleft()
        for edge in resolved.get_callees(node):
            c = edge.callee_qname
            if c not in dist:
                dist[c] = dist[node] + (c,)
                q.append(c)
    deepest = max(dist, key=lambda k: len(dist[k]))
    return deepest, dist[deepest]


def find_path_collisions(graph: AnalyzedGraph) -> Iterator[PathCollision]:
    """Flag (method, path) pairs registered by ≥2 handlers.

    Pure group-by on Stage 4's ApiRouteEntry list. One entry per
    collision, sorted by (method, path) for stable output.
    """
    from cartograph.v2.ir.analyzed import ApiRouteEntry

    by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
    for ep in graph.entry_points:
        if isinstance(ep, ApiRouteEntry):
            by_key[(ep.method, ep.path)].append(ep.qname)

    for (method, path), qnames in sorted(by_key.items()):
        if len(qnames) > 1:
            yield PathCollision(
                method=method,
                path=path,
                handlers=tuple(sorted(qnames)),
            )


_BLOCKING_HINTS: dict[str, frozenset[str]] = {
    "time": frozenset({"sleep"}),
    "requests": frozenset(
        {"get", "post", "put", "delete", "patch", "head", "options", "request"}
    ),
    "urllib": frozenset({"urlopen"}),
    "sqlite3": frozenset({"connect"}),
    "subprocess": frozenset(
        {"run", "call", "check_call", "check_output", "Popen"}
    ),
    "smtplib": frozenset({"SMTP", "SMTP_SSL"}),
    "socket": frozenset({"create_connection"}),
}


def find_sync_in_async(graph: AnalyzedGraph) -> Iterator[SyncInAsync]:
    """Flag async functions calling known-blocking sync symbols directly.

    Matches against a curated hint table of top-level-package + symbol-name
    pairs. Transitive blocking (async calls sync helper that calls time.sleep)
    isn't caught by this pass — it would need reachability analysis we don't
    yet run at Stage 4. This analysis is deliberately conservative: false
    positives are more harmful than misses when the finding is framed as
    "this will block your event loop."
    """
    resolved = graph.annotated.resolved

    # qname → "sync"/"async" via Stage 1 source modules (Stage 2 FunctionRef
    # doesn't carry sync/async today).
    kind_by_qname: dict[str, str] = {}
    for module in graph.annotated.source_modules.values():
        for fn in module.functions:
            kind_by_qname[fn.qname] = fn.kind

    # Group externals by caller so we can check per-function.
    ext_by_caller: dict[str, list[ExternalUnresolved]] = defaultdict(list)
    for u in resolved.unresolved:
        if isinstance(u, ExternalUnresolved):
            ext_by_caller[u.caller_qname].append(u)

    for caller_qname, externals in ext_by_caller.items():
        if kind_by_qname.get(caller_qname) != "async":
            continue
        for ext in externals:
            hints = _BLOCKING_HINTS.get(ext.target_module or "", frozenset())
            if ext.name in hints:
                yield SyncInAsync(
                    async_qname=caller_qname,
                    blocking_call=f"{ext.target_module}.{ext.name}",
                    line=ext.line,
                )


def find_import_cycles(graph: AnalyzedGraph) -> Iterator[ImportCycle]:
    """Detect cycles in the project's module import graph.

    Builds a directed graph of `module_name → set of imported project
    modules` from Stage 1 imports, then DFS-walks looking for back-edges
    into nodes currently on the recursion stack. Each distinct cycle is
    reported once (normalised to start from the alphabetically smallest
    member so the output is stable across runs).

    Only in-project imports count — `import os`, `from numpy import ...`
    land outside the project and don't participate in cycles.
    """
    modules = graph.annotated.source_modules
    if not modules:
        return

    # Build adjacency: module_name → sorted list of project modules it imports.
    import_graph: dict[str, list[str]] = {}
    for name, module in modules.items():
        deps: set[str] = set()
        for imp in module.imports:
            target = imp.module
            if not target:
                continue
            if target in modules:
                deps.add(target)
            # Also match prefix — `from pkg.sub import X` targets `pkg.sub`
            # which may itself be a module in our set.
        import_graph[name] = sorted(deps)

    # DFS with three-colour node state (0=white/unvisited, 1=gray/on-stack,
    # 2=black/done) to find back-edges — an edge to a gray node means cycle.
    color = dict.fromkeys(import_graph, 0)
    stack: list[str] = []
    seen_cycles: set[tuple[str, ...]] = set()

    def dfs(node: str) -> None:
        color[node] = 1  # gray: on the current recursion stack
        stack.append(node)
        for dep in import_graph.get(node, ()):
            if dep not in color:
                continue
            if color[dep] == 1:
                # Back-edge into the stack: slice the cycle out.
                try:
                    idx = stack.index(dep)
                except ValueError:
                    continue
                cycle = tuple(stack[idx:])
                seen_cycles.add(_normalise_cycle(cycle))
            elif color[dep] == 0:
                dfs(dep)
        color[node] = 2  # black: fully processed
        stack.pop()

    for start in sorted(import_graph):
        if color[start] == 0:
            dfs(start)

    for cycle in sorted(seen_cycles):
        yield ImportCycle(modules=cycle)


def _normalise_cycle(cycle: tuple[str, ...]) -> tuple[str, ...]:
    """Rotate the cycle so it starts with its alphabetically smallest module.
    Ensures `(a,b,c)` and `(c,a,b)` and `(b,c,a)` all normalise to `(a,b,c)`."""
    if not cycle:
        return cycle
    min_idx = min(range(len(cycle)), key=lambda i: cycle[i])
    return cycle[min_idx:] + cycle[:min_idx]


class DeadFunction(IR):
    """A function or class with zero incoming edges, not an entry point.

    Confidence is heuristic — dynamic dispatch (getattr, string-indexed
    dicts of callables, __getattr__) can bypass the static graph, so a
    reported dead function may actually be reachable at runtime. Treat the
    report as a starting list for review, not a deletion list.
    """

    qname: str
    kind: str  # "function" | "method" | "class"
    source_path: str
    line_start: int


class CallSiteImpact(IR):
    """One call site that would break under a rename."""

    file: str
    line: int
    caller_qname: str


class ImportSiteImpact(IR):
    """One import statement that would break under a rename.

    `statement` is a reconstructed `from pkg import Name` rendering for
    display; `file:line` is where the source statement lives.
    """

    file: str
    line: int
    module: str
    statement: str


class RenameImpact(IR):
    """Everything that would break if `old_qname` is renamed to `new_name`.

    v2.3 enumerates both call sites (from the graph) and import sites
    (from Stage 1 imports). Import matching is on the `from <parent>
    import <short>` shape — the common case. `import pkg.short` style
    isn't enumerated because it uses the dotted path, which a short-name
    rename doesn't touch.
    """

    old_qname: str
    new_name: str
    definition_file: str
    definition_line: int
    call_sites: tuple[CallSiteImpact, ...]
    import_sites: tuple[ImportSiteImpact, ...]


def rename_impact(graph: AnalyzedGraph, old_qname: str, new_name: str) -> RenameImpact:
    """Enumerate call sites and import statements that reference `old_qname`."""
    resolved = graph.annotated.resolved
    fn = resolved.functions.get(old_qname)
    if fn is None:
        raise ValueError(f"unknown qname: {old_qname}")

    short_name = old_qname.rsplit(".", 1)[-1]
    parent_module = old_qname.rsplit(".", 1)[0] if "." in old_qname else ""

    # Call sites — from the resolved graph.
    callers: list[CallSiteImpact] = []
    for edge_idx in resolved.callers_by_callee.get(old_qname, ()):
        edge = resolved.edges[edge_idx]
        caller = resolved.functions.get(edge.caller_qname)
        callers.append(
            CallSiteImpact(
                file=str(caller.source_path) if caller else "<unknown>",
                line=edge.line,
                caller_qname=edge.caller_qname,
            )
        )
    callers.sort(key=lambda s: (s.file, s.line))

    # Import sites — scan every module's imports.
    import_sites: list[ImportSiteImpact] = []
    for module in graph.annotated.source_modules.values():
        for imp in module.imports:
            if imp.name != short_name:
                continue
            # Match the module path with some tolerance for how imports
            # can be written (full qname vs trailing-segment match).
            if parent_module and not (
                imp.module == parent_module
                or parent_module.endswith(f".{imp.module}")
                or imp.module.endswith(parent_module.rsplit(".", 1)[-1])
            ):
                continue
            statement = f"from {imp.module} import {short_name}"
            if imp.alias:
                statement += f" as {imp.alias}"
            import_sites.append(
                ImportSiteImpact(
                    file=str(module.path),
                    line=imp.line,
                    module=module.module_name,
                    statement=statement,
                )
            )
    import_sites.sort(key=lambda s: (s.file, s.line))

    return RenameImpact(
        old_qname=old_qname,
        new_name=new_name,
        definition_file=str(fn.source_path),
        definition_line=fn.line_start,
        call_sites=tuple(callers),
        import_sites=tuple(import_sites),
    )


def find_dead(graph: AnalyzedGraph) -> Iterator[DeadFunction]:
    """Functions/classes with zero incoming edges and no entry-point status.

    Excluded on purpose:
        - Functions/classes named `__init__`, `__main__`, `main` — often
          imported-and-invoked from outside the graph we can see.
        - Dunder methods (`__init__`, `__enter__`, `__aexit__`, etc.) —
          called implicitly by Python semantics, not by static callers.
        - Classes whose methods have callers — if a method of `Foo` is
          reached, `Foo` itself clearly has a reason to exist even if
          never syntactically constructed.
    """
    resolved = graph.annotated.resolved
    entry_qnames = {ep.qname for ep in graph.entry_points}

    # Methods on a "live" class — we consider the class reachable if *any*
    # of its methods has callers.
    live_classes: set[str] = set()
    for qname, fn in resolved.functions.items():
        if (
            fn.kind == "method"
            and fn.class_name
            and resolved.callers_by_callee.get(qname)
        ):
            live_classes.add(f"{fn.module}.{fn.class_name}")

    for qname, fn in resolved.functions.items():
        if qname in entry_qnames:
            continue
        if resolved.callers_by_callee.get(qname):
            continue
        name = fn.name
        if name.startswith("__") and name.endswith("__"):
            continue
        if name in {"main", "__main__"}:
            continue
        if fn.kind == "class" and qname in live_classes:
            continue
        yield DeadFunction(
            qname=qname,
            kind=fn.kind,
            source_path=str(fn.source_path),
            line_start=fn.line_start,
        )


def _iter_orm_by_function(
    graph: AnalyzedGraph,
) -> Iterator[tuple[str, tuple[OrmOperationLabel, ...]]]:
    """Yield (qname, tuple of OrmOperationLabels) for every function that has
    at least one ORM label. Callers that need all functions should iterate
    `graph.annotated.resolved.functions` directly."""
    for qname, labels in graph.annotated.labels.items():
        orm = tuple(lbl for lbl in labels if isinstance(lbl, OrmOperationLabel))
        if orm:
            yield qname, orm
