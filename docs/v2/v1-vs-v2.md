# v1 vs v2 — exhaustive diff

Written for v1 maintainers and anyone who has internalised v1's implementation. Every difference that matters, from the shape of the pipeline down to ruff rules. If you're evaluating v2 and haven't worked on v1, read [`architecture.md`](./architecture.md) first — this doc assumes v1 knowledge.

## Positioning

v1 was "AI-powered code flow explorer." v2 sharpens it to **harnessing deterministic context for LLMs**, and every structural change below traces back to that line. Frozen typed IRs because LLMs (and humans) should not have to reverse-engineer stage contracts. Per-call-site labels because a summary loses the line number an agent needs to cite. Async-kind edges because `task.delay(x)` looks identical to a method call at the syntax layer. LSP resolution because the bits LLMs hallucinate are exactly the bits a type checker already knows.

## Pipeline shape

|  | v1 | v2 |
|---|---|---|
| Stages | 2 (parse → build), with annotate/discover inlined | 5 (extract → resolve → annotate → discover → present) |
| Boundaries | Mutable dataclasses, fields added organically | Frozen pydantic IRs, `extra=forbid`, `strict=True` |
| Orchestration | `parse_and_build()` function | `Pipeline` frozen dataclass of stage instances |
| Side effects | Mixed into parser + resolver | Isolated inside stage implementations |
| Error handling | Exceptions bubble; some swallowed | `Result[Ok, Err_]` + `TypeGuard`-narrowed unions |
| Concurrency | Serial | Async-batched LSP queries, semaphore-gated (50 in-flight default) |

## Stage 2 — resolve

| | v1 | v2 |
|---|---|---|
| Impl | `CallGraphBuilder` in `graph/call_graph.py` | LSP client to `ty server` |
| Algorithm | 7-pass cascade (self/MRO, import lookup, parameter types, local types, return types, ORM patterns, async dispatch) | Delegated to `ty` |
| LOC | ~600 | ~250 transport + ~250 resolver shell |
| Swappable | No | Yes, via `Resolver` protocol |
| Accuracy claim | README "~65%", no test | Pairwise overlap only, no accuracy claims |

## Caching

| | v1 | v2 |
|---|---|---|
| Stage 1 (extract) | None | Per-file blake2b-256 → JSON, atomic writes |
| Stage 2 (resolve) | None | Project fingerprint → JSON, atomic writes |
| Hash | n/a | blake2b-256 (≈2× faster than sha256) |
| Invalidation | All-or-nothing re-parse | Fingerprint mismatch = miss; otherwise hit |
| Cache versioning | n/a | Self-healing via `ValidationError → None` (stale entry = miss) |
| Partial invalidation | n/a | No (whole-graph Stage 2) — deferred until 50K+ file scale |
| Last-project-path | `~/.cartograph/last_project` | `~/.cartograph/last_project_v2` (separate file during transition) |

## Graph queries

| | v1 | v2 |
|---|---|---|
| `get_callees` | O(\|edges\|) — linear scan | O(1) via `callees_by_caller` index |
| `get_callers` | O(\|edges\|) | O(1) via `callers_by_callee` index |
| Index construction | Implicit, on-demand | Once in `ResolvedGraph.__init__` (frozen) |

## Stage 3 — annotate

| | v1 | v2 |
|---|---|---|
| When | During parse | After resolve (can consult the built graph) |
| Detector surface | `detect_entry_points`, `detect_async_boundary`, `annotate_call` | Single `annotate(graph, modules)` |
| Label type | `dict[str, Any]` | Discriminated union: `ApiRouteLabel`, `CeleryTaskLabel`, `DjangoSignalLabel`, `OrmOperationLabel`, … |
| ORM granularity | Per-call-site with line | Per-call-site with line (parity) |
| Adding a framework | Modify `core.py::build_registries()` + new detector | Add to `default_annotators()` in registry.py |

## Stage 4 — entry-point discovery

Both use the same topology rule: decorator + zero in-edges + ≥1 out-edges. v2 additionally consults Stage 3 labels to promote `DiscoveredEntry` into typed variants (`ApiRouteEntry`, `CeleryTaskEntry`, `SignalHandlerEntry`). v1's framework detectors emit `EntryPoint` directly, bypassing topology.

On fastapi corpus: v1 finds 466 entries, v2 finds 52 — v2's rule is stricter and returns fewer, tighter entries.

## Stage 5 — presentation

| | v1 | v2 |
|---|---|---|
| CLI rendering | `rich` tables/trees | Plain text for deterministic snapshotting |
| Web viewer | ELK.js (layout) + D3 (render) | Cytoscape.js + cytoscape-dagre (one lib) |
| Viewer on load | Empty until click | Auto-loads first entry's subgraph |
| Async edge visual | Single colour | Pink dashed with kind label (`delay`, `chord`, …) |
| JSON API | `JSONResponse` (stdlib json) | FastAPI's pydantic-core path (Rust) |
| LLM narration | `llm/narrator.py`, hand-rolled Claude/OpenAI/Ollama providers | `LlmPresenter` via pydantic-ai `Agent` |
| Sync→async bridge | n/a | `_run_sync` detects live loop, thread-pool fallback (Jupyter-safe) |
| Markdown pipe | `context` command | `context` command (parity) |
| JSON dump | `trace -o file.json` | `trace -o file.json` (parity) |
| Agent-native surface | n/a | FastMCP server over stdio (`carto2 mcp`) — 7 tools |

## IR details

| | v1 | v2 |
|---|---|---|
| Module count | `ProjectIndex.modules` | derived from `SyntacticModule.module_name` |
| Function kinds | `NodeType` enum (FUNCTION / METHOD / CLASS / ENTRY_POINT / EXTERNAL_CALL) | `FunctionRef.kind: Literal["function","method","class"]`; entry-point status moved to `EntryPoint` variants |
| Docstrings | `ParsedFunction.docstring` | `SyntacticFunction.docstring`, propagated to `FunctionRef.docstring` |
| Call classification | `FunctionCall.is_method_call` / `.is_async_dispatch` booleans | `CallKind` discriminated union: `PlainCall`, `MethodCall`, `AsyncDispatchCall`, `AsyncOrchestrationCall` |
| Async edges | `FunctionCall.async_type` | `Edge.async_kind: AsyncKind \| None` |
| Celery chain/chord/group | Recognized as `AsyncBoundaryType` | `AsyncOrchestrationCall` (dedicated variant) |
| Decorators | `ParsedFunction.decorators: list[str]` | `DecoratorSpec(name, args, kwargs)` in SyntacticFunction; `FunctionRef.decorators: tuple[str, ...]` (names only) |
| Branch tracking | `ParsedFunction.branches: list[ConditionalBranch]` | Condition encoded on `Edge.condition`, no per-function `branches` list |
| Imports | `ParsedImport` with `level` field | `SyntacticImport` with `level` (parity) |
| Unresolved calls | Untyped leftover list | `UnresolvedCall` discriminated union: `BuiltinUnresolved`, `ExternalUnresolved`, `LspUnresolved`, `UnknownUnresolved` |

## CLI surface

All v1 commands have v2 equivalents. Options may differ:

| Command | v1 | v2 |
|---|---|---|
| `init` | `carto init <path>` | `carto2 init <path> [--include-tests]` |
| `scan` | `carto scan <path>` | `carto2 scan [path]` (path optional after init) |
| `entries` | `carto entries [path]` | `carto2 entries [path] [--kind]` |
| `trace` | `carto trace [path] <fn> [-o] [-d]` | `carto2 trace <qname> [path] [--depth] [-o]` |
| `callers` | `carto callers [path] <fn>` | `carto2 callers <qname> [path]` |
| `search` | `carto search [path] <q>` | `carto2 search <q> [path] [--limit]` |
| `serve` | `carto serve [path] [-p]` | `carto2 serve [path] [--port] [--host]` |
| `explain` | `carto explain [path] [fn]` | `carto2 explain <qname> [path] [--depth] [--model]` |
| `context` | `carto context [path] [fn]` | `carto2 context [qname] [path] [--depth]` |
| `mcp` | — | `carto2 mcp [path]` (stdio MCP server, v2-only) |
| `benchmark` | — | `carto2 benchmark [path] [--targets]` |

Qname resolution logic matches: exact → suffix → substring, first hit.

## Dependencies

| | v1 | v2 |
|---|---|---|
| Required | click, rich, fastapi, uvicorn | v1 deps + pydantic, logfire, pydantic-ai, tree-sitter, tree-sitter-python, fastmcp |
| Dev-only | pytest, ruff, pre-commit | + pytest-asyncio |
| External binaries | None | `ty` on PATH |
| Package manager | Poetry | uv |
| pyproject format | `[tool.poetry]` | PEP 621 `[project]` |
| Build backend | poetry-core | hatchling |
| Requirements file | `requirements.txt` (stale) | Gone; deps declared in `pyproject.toml` |

## Type-system posture

| | v1 | v2 |
|---|---|---|
| `Optional[X]` | Mixed; some `Optional`, some `X \| None` | `X \| None` everywhere (ruff UP rule) |
| Generic Result type | n/a | `Result[T, E] = Ok[T] \| Err_[E]` |
| TypeGuards | n/a | `is_ok`, `is_err` both return `TypeGuard[...]` |
| Discriminated unions | Enum + isinstance dispatch | `Annotated[Union[...], Discriminator(field)]` |

## Observability

| | v1 | v2 |
|---|---|---|
| Logging | `logging` stdlib | `logfire.span(...)` per stage |
| Trace context | None | Project root, resolver name, edge counts emitted per span |

## Tooling & infra

| | v1 | v2 |
|---|---|---|
| Hash algo | n/a | blake2b-256 (cache keys) |
| CI Python | 3.12 | 3.11 minimum, 3.12+ tested |
| CI jobs | lint + single test job (v1 suite only) | lint + test-v1 + test-v2 (with `ty` install) |
| Pre-commit | ruff | ruff (same) |
| Ruff rules | E F W I N UP B SIM RUF | Same |
| `is_ok` / `is_err` | n/a | `TypeGuard` narrowing |

## What was evaluated and dropped during v2

- **Pyright oracle** — external Node binary, cut early.
- **PyreflyResolver** — benchmarked head-to-head; ty strictly better out of the box (487 edges @1.7s vs 12 @98s on fastapi without pyrefly project config).
- **AstExtractor** — TreesitterExtractor matched edge count + wall time and tolerates partial syntax.
- **rapidfuzz + fzf qname scorer** — built, reverted as overengineering. Three-tier exact/suffix/substring is enough.
- **SQLite / pickle / compressed cache** — considered, rejected. 10K entries fit JSON-on-disk cleanly.
- **Cache version header** — redundant with self-healing `ValidationError → None`.

## What stayed from v1

- Topology-based entry discovery (algorithm ported verbatim, noise-decorator list preserved).
- Framework-agnostic core — the six framework annotators are complements, not requirements.
- LLM-oriented output as a product goal.
- Shared `tests/fixtures/` between v1 and v2 suites.
- Python 3.11+ as the supported range.
