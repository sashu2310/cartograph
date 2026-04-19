"""The Discoverer protocol — Stage 4's contract.

A Discoverer takes an AnnotatedGraph (topology + semantic labels) and produces
the list of EntryPoints. The cartograph-specific one, TopologyDiscoverer, uses
graph topology + decorator heuristics (ADR: this is the project's one genuinely
novel algorithm).
"""

from __future__ import annotations

from typing import Protocol

from cartograph.v2.ir.analyzed import EntryPoint
from cartograph.v2.ir.annotated import AnnotatedGraph


class Discoverer(Protocol):
    name: str

    def discover(self, graph: AnnotatedGraph) -> tuple[EntryPoint, ...]:
        """Identify entry points from the annotated graph. Pure function."""
        ...
