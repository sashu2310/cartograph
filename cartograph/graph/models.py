"""Core data models for CARTOGRAPH flow DAGs."""

from dataclasses import dataclass, field
from enum import Enum


class NodeType(Enum):
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    ENTRY_POINT = "entry_point"
    EXTERNAL_CALL = "external_call"


class EdgeType(Enum):
    CALLS = "calls"
    CONDITIONAL = "conditional"
    ASYNC_DISPATCH = "async_dispatch"
    SIGNAL = "signal"
    ORM_OPERATION = "orm_operation"
    EXCEPTION_HANDLER = "exception_handler"


class EntryPointType(Enum):
    API_ROUTE = "api_route"
    CELERY_TASK = "celery_task"
    CELERY_BEAT = "celery_beat"
    MANAGEMENT_COMMAND = "management_command"
    SIGNAL_HANDLER = "signal_handler"


class AsyncBoundaryType(Enum):
    CELERY_DELAY = "celery_delay"
    CELERY_APPLY_ASYNC = "celery_apply_async"
    CELERY_CHAIN = "celery_chain"
    CELERY_CHORD = "celery_chord"
    CELERY_GROUP = "celery_group"


class ORMOperation(Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"


@dataclass
class FunctionCall:
    """A function/method call found within a function body."""

    name: str
    qualified_name: str | None = None
    line: int = 0
    is_method_call: bool = False
    receiver: str | None = None
    args_count: int = 0
    is_async_dispatch: bool = False
    async_type: AsyncBoundaryType | None = None


@dataclass
class ConditionalBranch:
    """A conditional branch (if/elif/else) within a function."""

    condition: str | None = None
    line: int = 0
    calls: list[FunctionCall] = field(default_factory=list)
    is_else: bool = False


@dataclass
class ParsedFunction:
    """A function/method extracted from AST parsing."""

    name: str
    qualified_name: str
    file_path: str
    line_start: int
    line_end: int
    type: NodeType = NodeType.FUNCTION
    docstring: str | None = None
    decorators: list[str] = field(default_factory=list)
    decorator_details: list[dict] = field(default_factory=list)
    calls: list[FunctionCall] = field(default_factory=list)
    branches: list[ConditionalBranch] = field(default_factory=list)
    class_name: str | None = None
    module_path: str | None = None
    imports: dict[str, str] = field(default_factory=dict)
    annotations: dict = field(default_factory=dict)


@dataclass
class ParsedImport:
    """An import statement extracted from a module."""

    module: str
    name: str
    alias: str | None = None
    is_relative: bool = False
    level: int = 0


@dataclass
class ParsedModule:
    """A parsed Python module (file)."""

    file_path: str
    module_path: str
    functions: list[ParsedFunction] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    imports: list[ParsedImport] = field(default_factory=list)
    file_hash: str | None = None


@dataclass
class Node:
    """A node in the flow DAG."""

    id: str
    name: str
    type: NodeType
    file_path: str
    line_start: int
    line_end: int
    docstring: str | None = None
    decorators: list[str] = field(default_factory=list)
    annotations: dict = field(default_factory=dict)
    entry_point_type: EntryPointType | None = None
    http_method: str | None = None
    url_pattern: str | None = None
    celery_queue: str | None = None
    orm_operations: list[dict] = field(default_factory=list)


@dataclass
class Edge:
    """An edge in the flow DAG."""

    source_id: str
    target_id: str
    type: EdgeType
    condition: str | None = None
    label: str | None = None
    async_boundary: AsyncBoundaryType | None = None


@dataclass
class EntryPoint:
    """An entry point into the system (API route, Celery task, etc.)."""

    node_id: str
    type: EntryPointType
    trigger: str
    description: str | None = None


@dataclass
class FlowDAG:
    """A complete flow DAG starting from an entry point."""

    id: str
    entry_point: EntryPoint
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    total_nodes: int = 0
    total_branches: int = 0

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node
        self.total_nodes = len(self.nodes)
        if node.file_path not in self.files_touched:
            self.files_touched.append(node.file_path)

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)
        if edge.type == EdgeType.CONDITIONAL:
            self.total_branches += 1


@dataclass
class ProjectIndex:
    """Index of all parsed data for a project."""

    root_path: str
    modules: dict[str, ParsedModule] = field(default_factory=dict)
    entry_points: list[EntryPoint] = field(default_factory=list)
    flow_dags: dict[str, FlowDAG] = field(default_factory=dict)

    @property
    def total_functions(self) -> int:
        return sum(len(m.functions) for m in self.modules.values())

    @property
    def total_modules(self) -> int:
        return len(self.modules)
