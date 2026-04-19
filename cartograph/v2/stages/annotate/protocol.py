"""The Annotator protocol — Stage 3's contract.

An Annotator looks at a ResolvedGraph (and the originating SyntacticModules, for
access to decorators and class bases) and produces per-function semantic labels.

Multiple Annotators run in parallel during Stage 3. Their output label dicts
are merged before Stage 4 consumes the AnnotatedGraph.
"""

from __future__ import annotations

from typing import Protocol

from cartograph.v2.ir.annotated import SemanticLabel
from cartograph.v2.ir.resolved import ResolvedGraph
from cartograph.v2.ir.syntactic import SyntacticModule


class Annotator(Protocol):
    framework: str

    def annotate(
        self,
        graph: ResolvedGraph,
        modules: dict[str, SyntacticModule],
    ) -> dict[str, tuple[SemanticLabel, ...]]:
        """Return qname → labels for every function this annotator recognizes.

        Pure function: no mutation of inputs; annotators that find nothing
        return an empty dict.
        """
        ...
