"""Rename-impact analysis — call sites and import statements that would break.

Read-only: produces a plan, never modifies files.
"""

from __future__ import annotations

from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.base import IR


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
