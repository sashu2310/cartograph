"""Sync-in-async detection.

Curated blocking-symbol table (not heuristics). Static analysis can't
prove a sync call blocks; we opt for precision over recall.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator

from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.base import IR
from cartograph.v2.ir.resolved import ExternalUnresolved


class SyncInAsync(IR):
    """An async function calls a known-blocking sync symbol directly.

    Static analysis can't prove a given sync call is blocking, so we
    only flag a curated set of well-known offenders (`time.sleep`,
    `requests.*`, `urllib.urlopen`, `subprocess.*`, `sqlite3.connect`).
    Transitive blocking (async -> sync -> blocking) isn't detected in
    this pass.
    """

    async_qname: str
    blocking_call: str
    line: int


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

    # qname -> "sync"/"async" via Stage 1 source modules (Stage 2 FunctionRef
    # doesn't carry sync/async today).
    kind_by_qname: dict[str, str] = {}
    for module in graph.annotated.source_modules.values():
        for fn in module.functions:
            kind_by_qname[fn.qname] = fn.kind

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
