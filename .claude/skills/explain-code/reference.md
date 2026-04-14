# Codebase Context Reference

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| Parsing | stdlib `ast` module |
| CLI | Click 8.0 + Rich 13.0 |
| Web | FastAPI 0.115 + Uvicorn |
| LLM | Anthropic SDK / OpenAI SDK / httpx (Ollama) |
| Testing | pytest 8.0 |
| Linting | ruff 0.11 |

## Architecture

Three-layer parser pipeline:

```
Files → PythonAdapter.parse_file() → ParsedModule
ParsedModules → FrameworkDetectors → annotated ParsedModules
ParsedModules → CallGraphBuilder.build() → CallGraph
CallGraph → CLI / Web API / LLM narrator
```

## Key Contracts

**LanguageAdapter** (`cartograph/parser/protocols.py`):
- `parse_file(path) → ParsedModule`
- `resolve_import(import, project_root) → qualified_name`
- Properties: `language_id`, `file_extensions`

**FrameworkDetector** (`cartograph/parser/protocols.py`):
- `detect_entry_points(module) → list[EntryPoint]`
- `detect_async_boundary(call) → AsyncBoundaryType | None`
- `annotate_call(call, module) → FunctionCall`

## Module Responsibilities

| Module | Does | Doesn't |
|--------|------|---------|
| `parser/` | Extract structure from source files | Resolve cross-file calls |
| `graph/call_graph.py` | Resolve calls across files | Parse source code |
| `graph/models.py` | Define data structures | Contain business logic |
| `core.py` | Orchestrate parse → build pipeline | Know about CLI/Web |
| `cli.py` | User interaction, output formatting | Parsing or graph building |
| `web/` | HTTP API, JSON serialization | Direct graph manipulation |
| `llm/` | Narrate flows using AI | Modify graph data |

## Data Model Hierarchy

```
ProjectIndex
├── modules: dict[str, ParsedModule]
│   ├── file_path, module_path
│   ├── functions: list[ParsedFunction]
│   │   ├── name, qualified_name, type (FUNCTION/METHOD)
│   │   ├── calls: list[FunctionCall]
│   │   ├── branches: list[ConditionalBranch]
│   │   └── local_types: dict[str, str]  (type inference)
│   ├── classes: list[str]
│   └── imports: list[ParsedImport]
└── entry_points: list[EntryPoint]

CallGraph
├── functions: dict[str, ParsedFunction]
├── edges: list[CallEdge]
│   ├── caller, callee (qualified names)
│   ├── call: FunctionCall
│   └── is_cross_file: bool
└── unresolved: list[UnresolvedCall]
```
