"""The Presenter protocol — Stage 5's contract.

A Presenter turns an AnalyzedGraph into bytes for a specific output target —
CLI text, JSON, HTML, markdown, mermaid, dot, etc. Presenters are independent:
adding a new one never touches the other stages.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from cartograph.v2.ir.analyzed import AnalyzedGraph

OutputFormat = Literal["cli", "json", "html", "markdown", "mermaid", "dot"]


class Presenter(Protocol):
    name: str
    output_format: OutputFormat

    def render(self, graph: AnalyzedGraph, options: dict[str, Any]) -> bytes:
        """Render the final graph. Returns bytes (utf-8 for text formats)."""
        ...
