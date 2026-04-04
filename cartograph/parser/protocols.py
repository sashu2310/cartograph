"""Protocols defining the contracts for language adapters and framework detectors.

These protocols are the abstraction boundary between language-specific parsing
and the universal graph layer. Everything above this boundary (language parsers,
framework detectors) is pluggable. Everything below it (graph builder, LLM layer,
CLI, VS Code extension) never changes when a new language is added.
"""

from typing import Protocol, runtime_checkable

from cartograph.graph.models import (
    AsyncBoundaryType,
    EntryPoint,
    FunctionCall,
    ParsedImport,
    ParsedModule,
)


@runtime_checkable
class LanguageAdapter(Protocol):
    """Parses source files of a specific language into uniform IR.

    Each language adapter knows the syntax of its language (Python def,
    Java public void, Go func) but outputs the same ParsedModule regardless.
    The graph layer never knows which adapter produced the data.
    """

    @property
    def language_id(self) -> str:
        """Unique identifier: 'python', 'java', 'go', 'javascript'."""
        ...

    @property
    def file_extensions(self) -> set[str]:
        """File extensions this adapter handles: {'.py'}, {'.java'}."""
        ...

    def parse_file(self, file_path: str, module_path: str) -> ParsedModule | None:
        """Parse a single file into uniform IR.

        Returns None if the file can't be parsed (syntax error, encoding issue).
        Graceful degradation — never raises.
        """
        ...

    def resolve_import(
        self, imp: ParsedImport, source_file: str, project_root: str
    ) -> str | None:
        """Resolve an import to an absolute file path.

        Returns None if the import can't be resolved (external package,
        dynamic import). Best-effort — unresolved imports are marked as
        EXTERNAL_CALL in the graph, not treated as errors.
        """
        ...


@runtime_checkable
class FrameworkDetector(Protocol):
    """Detects framework-specific patterns in parsed modules.

    Framework detectors examine the uniform IR (ParsedModule) — decorators,
    function names, call patterns — and annotate them with semantic meaning.
    Multiple detectors can run on the same module (composable).
    """

    @property
    def framework_id(self) -> str:
        """Unique identifier: 'django_ninja', 'celery', 'spring_boot'."""
        ...

    def detect_entry_points(self, module: ParsedModule) -> list[EntryPoint]:
        """Find framework-specific entry points in a module.

        Examples: @api_controller → API route, @task → Celery task,
        @RestController → Spring endpoint.
        """
        ...

    def detect_async_boundary(self, call: FunctionCall) -> AsyncBoundaryType | None:
        """Check if a function call is an async dispatch.

        Examples: .delay() → Celery async, @Async → Spring async,
        go func() → goroutine.
        """
        ...

    def annotate_call(self, call: FunctionCall) -> dict | None:
        """Add framework-specific metadata to a call.

        Examples: .filter() → {operation: "read", model: "Sensor"},
        .save() → {operation: "write", model: "Equipment"}.
        Returns None if the call has no framework significance.
        """
        ...
