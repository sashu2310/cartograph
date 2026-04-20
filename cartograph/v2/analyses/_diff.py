"""Set-difference between two AnalyzedGraph snapshots. No I/O."""

from __future__ import annotations

from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.base import IR


class EdgeKey(IR):
    # `line` in the key so two distinct call sites to the same callee
    # don't collapse. `async_kind` so `foo()` → `foo.delay()` shows as
    # remove + add, not unchanged.
    caller_qname: str
    callee_qname: str
    line: int
    async_kind: str | None = None


class EntryPointDelta(IR):
    qname: str
    from_kind: str
    to_kind: str


class LabelDelta(IR):
    # label_json is the full model_dump_json() so new fields on a label
    # variant flow through the diff without code changes here.
    qname: str
    label_kind: str
    label_json: str


class FunctionDelta(IR):
    qname: str
    kind: str  # "function" | "method" | "class"
    source_path: str
    line_start: int


class GraphDiff(IR):

    from_sha: str
    to_sha: str
    added_edges: tuple[EdgeKey, ...]
    removed_edges: tuple[EdgeKey, ...]
    added_entries: tuple[str, ...]
    removed_entries: tuple[str, ...]
    entry_kind_changes: tuple[EntryPointDelta, ...]
    added_labels: tuple[LabelDelta, ...]
    removed_labels: tuple[LabelDelta, ...]
    added_functions: tuple[FunctionDelta, ...]
    removed_functions: tuple[FunctionDelta, ...]

    @property
    def is_empty(self) -> bool:
        return not (
            self.added_edges
            or self.removed_edges
            or self.added_entries
            or self.removed_entries
            or self.entry_kind_changes
            or self.added_labels
            or self.removed_labels
            or self.added_functions
            or self.removed_functions
        )


def diff_graphs(
    from_graph: AnalyzedGraph,
    to_graph: AnalyzedGraph,
    *,
    from_sha: str,
    to_sha: str,
) -> GraphDiff:
    added_edges, removed_edges = _edge_diff(from_graph, to_graph)
    added_entries, removed_entries, kind_changes = _entry_diff(from_graph, to_graph)
    added_labels, removed_labels = _label_diff(from_graph, to_graph)
    added_fns, removed_fns = _function_diff(from_graph, to_graph)

    return GraphDiff(
        from_sha=from_sha,
        to_sha=to_sha,
        added_edges=added_edges,
        removed_edges=removed_edges,
        added_entries=added_entries,
        removed_entries=removed_entries,
        entry_kind_changes=kind_changes,
        added_labels=added_labels,
        removed_labels=removed_labels,
        added_functions=added_fns,
        removed_functions=removed_fns,
    )


def _edge_key_sort(e: EdgeKey) -> tuple:
    return (e.caller_qname, e.callee_qname, e.line, e.async_kind or "")


def _edge_diff(
    a: AnalyzedGraph, b: AnalyzedGraph
) -> tuple[tuple[EdgeKey, ...], tuple[EdgeKey, ...]]:
    a_keys = {_edge_to_key(e) for e in a.annotated.resolved.edges}
    b_keys = {_edge_to_key(e) for e in b.annotated.resolved.edges}
    added = tuple(
        sorted(
            (
                EdgeKey(**dict(zip(_EDGE_FIELDS, k, strict=True)))
                for k in b_keys - a_keys
            ),
            key=_edge_key_sort,
        )
    )
    removed = tuple(
        sorted(
            (
                EdgeKey(**dict(zip(_EDGE_FIELDS, k, strict=True)))
                for k in a_keys - b_keys
            ),
            key=_edge_key_sort,
        )
    )
    return added, removed


_EDGE_FIELDS = ("caller_qname", "callee_qname", "line", "async_kind")


def _edge_to_key(edge) -> tuple:
    return (edge.caller_qname, edge.callee_qname, edge.line, edge.async_kind)


def _entry_diff(
    a: AnalyzedGraph, b: AnalyzedGraph
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[EntryPointDelta, ...]]:
    a_by_qname = {ep.qname: ep.kind for ep in a.entry_points}
    b_by_qname = {ep.qname: ep.kind for ep in b.entry_points}
    a_names = set(a_by_qname)
    b_names = set(b_by_qname)

    added = tuple(sorted(b_names - a_names))
    removed = tuple(sorted(a_names - b_names))

    kind_changes = tuple(
        sorted(
            (
                EntryPointDelta(qname=q, from_kind=a_by_qname[q], to_kind=b_by_qname[q])
                for q in a_names & b_names
                if a_by_qname[q] != b_by_qname[q]
            ),
            key=lambda d: d.qname,
        )
    )
    return added, removed, kind_changes


def _label_diff(
    a: AnalyzedGraph, b: AnalyzedGraph
) -> tuple[tuple[LabelDelta, ...], tuple[LabelDelta, ...]]:
    a_labels = _flatten_labels(a)
    b_labels = _flatten_labels(b)
    added = tuple(
        sorted(
            (
                LabelDelta(qname=q, label_kind=kind, label_json=j)
                for (q, kind, j) in b_labels - a_labels
            ),
            key=lambda d: (d.qname, d.label_kind, d.label_json),
        )
    )
    removed = tuple(
        sorted(
            (
                LabelDelta(qname=q, label_kind=kind, label_json=j)
                for (q, kind, j) in a_labels - b_labels
            ),
            key=lambda d: (d.qname, d.label_kind, d.label_json),
        )
    )
    return added, removed


def _flatten_labels(graph: AnalyzedGraph) -> set[tuple[str, str, str]]:
    flat: set[tuple[str, str, str]] = set()
    for qname, labels in graph.annotated.labels.items():
        for label in labels:
            flat.add((qname, label.kind, label.model_dump_json()))
    return flat


def _function_diff(
    a: AnalyzedGraph, b: AnalyzedGraph
) -> tuple[tuple[FunctionDelta, ...], tuple[FunctionDelta, ...]]:
    a_fns = a.annotated.resolved.functions
    b_fns = b.annotated.resolved.functions
    added = tuple(
        sorted(
            (_to_fn_delta(b_fns[q]) for q in set(b_fns) - set(a_fns)),
            key=lambda f: f.qname,
        )
    )
    removed = tuple(
        sorted(
            (_to_fn_delta(a_fns[q]) for q in set(a_fns) - set(b_fns)),
            key=lambda f: f.qname,
        )
    )
    return added, removed


def _to_fn_delta(fn) -> FunctionDelta:
    return FunctionDelta(
        qname=fn.qname,
        kind=fn.kind,
        source_path=str(fn.source_path),
        line_start=fn.line_start,
    )
