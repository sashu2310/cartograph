"""Blast radius analyzer — pure computation, no IO beyond optional test index."""

from collections import deque
from pathlib import Path

from cartograph.blast.diff import functions_in_files
from cartograph.blast.models import (
    AffectedEntryPoint,
    AffectedFunction,
    AffectedTest,
    BlastInputKind,
    BlastRadiusReport,
    BlastStats,
    ImpactSeverity,
)
from cartograph.blast.tests_index import TestIndex
from cartograph.graph.call_graph import CallGraph
from cartograph.graph.models import ProjectIndex


class UnknownQnameError(Exception):
    def __init__(self, qname: str) -> None:
        self.qname = qname
        super().__init__(f"Unknown function qname: {qname}")


class BlastAnalyzer:
    def __init__(
        self,
        graph: CallGraph,
        index: ProjectIndex,
        test_index: TestIndex | None = None,
    ) -> None:
        self._graph = graph
        self._index = index
        self._test_index = test_index

    def analyze_files(
        self, changed_files: list[Path], max_depth: int = 10
    ) -> BlastRadiusReport:
        """Find changed_qnames from functions_in_files, then call analyze_functions."""
        changed_qnames = functions_in_files(self._index, changed_files)
        report = self._run_bfs(
            changed_qnames=changed_qnames,
            input_kind=BlastInputKind.FILES,
            changed_files=[str(f) for f in changed_files],
            max_depth=max_depth,
        )
        return report

    def analyze_functions(
        self, changed_qnames: list[str], max_depth: int = 10
    ) -> BlastRadiusReport:
        """BFS upstream and downstream from changed_qnames."""
        # Validate all qnames exist
        for qname in changed_qnames:
            if qname not in self._graph.functions:
                raise UnknownQnameError(qname)

        return self._run_bfs(
            changed_qnames=changed_qnames,
            input_kind=BlastInputKind.FUNCTIONS,
            changed_files=[],
            max_depth=max_depth,
        )

    def _run_bfs(
        self,
        changed_qnames: list[str],
        input_kind: BlastInputKind,
        changed_files: list[str],
        max_depth: int,
    ) -> BlastRadiusReport:
        changed_set = set(changed_qnames)

        # Track best result for each affected qname: qname -> AffectedFunction
        # A function appears at most once, minimum depth wins
        affected: dict[str, AffectedFunction] = {}

        # BFS downstream: follow callees
        # Queue entries: (qname, depth, path_from_change)
        visited_down: set[str] = set(changed_qnames)
        queue: deque[tuple[str, int, list[str]]] = deque()

        for start in changed_qnames:
            for edge in self._graph.get_callees(start):
                neighbor = edge.callee
                if neighbor in changed_set:
                    continue
                if neighbor not in visited_down:
                    visited_down.add(neighbor)
                    path = [start, neighbor]
                    queue.append((neighbor, 1, path))

        while queue:
            qname, depth, path = queue.popleft()
            if depth > max_depth:
                continue

            _update_affected(affected, qname, ImpactSeverity.DOWNSTREAM, depth, path)

            if depth < max_depth:
                for edge in self._graph.get_callees(qname):
                    neighbor = edge.callee
                    if neighbor in changed_set or neighbor in visited_down:
                        continue
                    visited_down.add(neighbor)
                    queue.append((neighbor, depth + 1, [*path, neighbor]))

        # BFS upstream: follow callers
        visited_up: set[str] = set(changed_qnames)
        queue = deque()

        for start in changed_qnames:
            for edge in self._graph.get_callers(start):
                neighbor = edge.caller
                if neighbor in changed_set:
                    continue
                if neighbor not in visited_up:
                    visited_up.add(neighbor)
                    path = [start, neighbor]
                    queue.append((neighbor, 1, path))

        while queue:
            qname, depth, path = queue.popleft()
            if depth > max_depth:
                continue

            _update_affected(affected, qname, ImpactSeverity.UPSTREAM, depth, path)

            if depth < max_depth:
                for edge in self._graph.get_callers(qname):
                    neighbor = edge.caller
                    if neighbor in changed_set or neighbor in visited_up:
                        continue
                    visited_up.add(neighbor)
                    queue.append((neighbor, depth + 1, [*path, neighbor]))

        # Add DIRECT entries for each changed function so consumers can iterate
        # affected_functions uniformly (changed + downstream + upstream).
        # DIRECT always wins over DOWNSTREAM/UPSTREAM for the same qname.
        for qname in changed_qnames:
            module = qname.rsplit(".", 1)[0] if "." in qname else qname
            affected[qname] = AffectedFunction(
                qualified_name=qname,
                module=module,
                severity=ImpactSeverity.DIRECT,
                depth=0,
                path_from_change=[qname],
            )

        affected_functions = list(affected.values())

        # Entry point detection
        affected_qnames_all = {f.qualified_name for f in affected_functions}
        affected_entry_points: list[AffectedEntryPoint] = []

        for ep in self._index.entry_points:
            if ep.node_id not in affected_qnames_all:
                continue
            # Determine reached_via path
            if ep.node_id in changed_set:
                reached_via = [ep.node_id]
            else:
                af = affected.get(ep.node_id)
                reached_via = af.path_from_change if af else [ep.node_id]

            affected_entry_points.append(
                AffectedEntryPoint(
                    qualified_name=ep.node_id,
                    entry_point_type=ep.type.value,
                    trigger=ep.trigger,
                    reached_via=reached_via,
                )
            )

        # Test matching
        affected_tests: list[AffectedTest] = []
        if self._test_index is not None:
            # Collect all qnames in blast radius (changed + affected)
            blast_qnames = changed_set | {f.qualified_name for f in affected_functions}

            # For each in-radius qname, look up tests that cover it
            test_to_covers: dict[str, list[str]] = {}
            for func_qname in blast_qnames:
                for test_qname in self._test_index.tests_by_target.get(func_qname, []):
                    if test_qname not in test_to_covers:
                        test_to_covers[test_qname] = []
                    test_to_covers[test_qname].append(func_qname)

            for test_qname, covers in test_to_covers.items():
                test_file = self._test_index.test_files.get(test_qname, "")
                affected_tests.append(
                    AffectedTest(
                        test_qualified_name=test_qname,
                        test_file=test_file,
                        covers=covers,
                    )
                )

        downstream_count = sum(
            1 for f in affected_functions if f.severity == ImpactSeverity.DOWNSTREAM
        )
        upstream_count = sum(
            1 for f in affected_functions if f.severity == ImpactSeverity.UPSTREAM
        )

        # max_depth only considers non-DIRECT entries (DIRECT is depth 0 by def)
        non_direct_depths = [
            f.depth for f in affected_functions if f.severity != ImpactSeverity.DIRECT
        ]

        stats = BlastStats(
            total_changed_functions=len(changed_qnames),
            total_downstream=downstream_count,
            total_upstream=upstream_count,
            total_entry_points_hit=len(affected_entry_points),
            total_tests_affected=len(affected_tests),
            max_depth=max(non_direct_depths, default=0),
        )

        return BlastRadiusReport(
            input_kind=input_kind,
            changed_files=changed_files,
            changed_functions=list(changed_qnames),
            affected_functions=affected_functions,
            affected_entry_points=affected_entry_points,
            affected_tests=affected_tests,
            stats=stats,
        )


def _update_affected(
    affected: dict[str, AffectedFunction],
    qname: str,
    severity: ImpactSeverity,
    depth: int,
    path: list[str],
) -> None:
    """Insert or update AffectedFunction, keeping minimum depth."""
    existing = affected.get(qname)
    if existing is None or depth < existing.depth:
        module = qname.rsplit(".", 1)[0] if "." in qname else qname
        affected[qname] = AffectedFunction(
            qualified_name=qname,
            module=module,
            severity=severity,
            depth=depth,
            path_from_change=list(path),
        )
