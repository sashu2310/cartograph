"""Response models for `/api/*`. Shapes are the SPA contract."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class Stats(BaseModel):
    total_modules: int
    total_functions: int
    total_edges: int
    total_unresolved: int
    total_entry_points: int


class EntryItem(BaseModel):
    node_id: str
    type: str
    trigger: str
    description: str | None = None
    module: str


class OverviewResponse(BaseModel):
    project_name: str
    stats: Stats
    entry_points_by_type: dict[str, list[EntryItem]]


class FunctionNode(BaseModel):
    name: str
    qualified_name: str
    file: str
    line_start: int
    line_end: int
    type: str
    decorators: list[str] = []
    docstring: str = ""
    annotations: dict[str, Any] = {}
    has_callees: bool
    branches: list[Any] = []
    expandable: bool = False


class EdgeEntry(BaseModel):
    source: str
    target: str
    type: str
    async_type: str | None = None
    is_cross_file: bool
    line: int
    condition: str | None = None


class GraphMetadata(BaseModel):
    total_nodes: int
    total_edges: int
    files_touched: list[str]
    total_files: int
    async_boundaries: int


class GraphResponse(BaseModel):
    entry_point: str
    nodes: dict[str, FunctionNode]
    edges: list[EdgeEntry]
    metadata: GraphMetadata


class CallerEntry(BaseModel):
    qualified_name: str
    name: str
    file: str
    line_start: int
    type: str
    is_cross_file: bool


class CallersResponse(BaseModel):
    target: str
    callers: list[CallerEntry]


class SearchHit(BaseModel):
    qualified_name: str
    name: str
    file: str
    type: str
    is_entry_point: bool


class SearchResponse(BaseModel):
    query: str
    results: list[SearchHit]


class LlmStatusResponse(BaseModel):
    available: bool


class NarrateResponse(BaseModel):
    narrative: str | None = None
    model: str | None = None
    error: str | None = None
