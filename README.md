# CARTOGRAPH

**Scan any Python codebase. See every flow. Pipe to Claude.**

Cartograph is a static analysis tool that maps codebases into navigable flows — entry points, call chains, conditional branches, cross-file dependencies. It discovers entry points from graph topology (not hardcoded decorators), builds a type-aware call graph, and outputs structured context that reduces LLM token usage by 100-280x.

```bash
pip install cartograph-code

carto scan ./your-project             # scan once, cached after
carto entries                         # list all entry points
carto trace "checkout"                # trace a call tree
carto context | claude                # pipe to any LLM
carto context "deploy" | claude       # scoped flow context
```

---

## Real Output — Parsing Open Source Projects

### Sentry (Django + Celery — 40K stars, custom framework abstractions)

```
$ cartograph summary ./sentry/src

Modules:        4,415
Functions:      30,926
Entry points:   788 (52 via detectors + 736 topology-discovered)
Resolved calls: 37,659
```

Sentry uses custom decorators (`@instrumented_task`, `@cell_silo_endpoint`) that no static analyzer knows about. Cartograph's topology-based discovery finds them anyway — **788 entry points without a single line of Sentry-specific code.**

### Polar (FastAPI — billing/subscriptions platform)

```
$ cartograph summary ./polar/server

Modules:        914
Functions:      6,350
Entry points:   600
Resolved calls: 6,327
```

```
$ cartograph trace ./polar/server "get_claim_info" --depth 2

Found: polar.customer_seat.endpoints.get_claim_info
File: polar/customer_seat/endpoints.py:323
Outgoing calls: 7 (7 cross-file, 0 async)

get_claim_info polar/customer_seat/endpoints.py:323
├── → SeatService.get_seat_by_token polar/customer_seat/service.py
│   ├── → CustomerSeatRepository.get_by_invitation_token polar/customer_seat/repository.py
│   ├── → CustomerSeatRepository.get_eager_options polar/customer_seat/repository.py
│   ├── ├─ if not seat or seat.is_revoked() or seat.is_claimed()
│   └── ├─ if seat.invitation_token_expires_at and seat.invitation_token_e...
├── → SeatService.check_seat_feature_enabled polar/customer_seat/service.py
│   ├── → OrganizationRepository.get_by_id polar/organization/repository.py
│   ├── → FeatureNotEnabled
│   ├── ├─ if not organization
│   │   └── → FeatureNotEnabled
│   └── ├─ if not organization.feature_settings.get('seat_based_pricing_en...
│       └── → FeatureNotEnabled
├── → OrganizationRepository.get_by_id polar/organization/repository.py
├── → SeatClaimInfo, → ResourceNotFound (×3, conditional)
├── ├─ if not seat → ResourceNotFound
├── ├─ else → ResourceNotFound (no subscription/order)
├── ├─ if not organization → ResourceNotFound
└── ├─ if seat.email / elif seat.member / elif seat.customer

Reachable: 6 functions across 5 files
```

### Dagster (orchestration framework — 12K stars, zero framework detectors)

```
$ cartograph summary ./dagster/python_modules/dagster/dagster

Modules:        790
Functions:      11,533
Entry points:   255 (all topology-discovered: @public, @schedule_cli.command, @job_cli.command...)
Resolved calls: 6,919
```

Zero Dagster-specific code in Cartograph. Every entry point found via graph topology.

### Prefect (orchestration framework — 20K stars)

```
$ cartograph summary ./prefect/src/prefect

Modules:        690
Functions:      6,280
Entry points:   396 (183 FastAPI routes + 213 topology-discovered)
Resolved calls: 2,821
```

### How Entry Point Discovery Works

Cartograph discovers entry points two ways:

1. **Framework detectors** — recognize `@app.get`, `@shared_task`, `@receiver`, etc. Produce rich labels ("GET /api/users", "Celery task: send_email").

2. **Topology discovery** — after the call graph is built, find functions with zero incoming edges + outgoing calls + a decorator. These are functions the framework calls but no project code calls. **Works on any framework without configuration.**

Framework detectors are optional enrichment. Topology does the heavy lifting.

---

## Symbols

`→` = function call | `⚡` = async boundary (Celery) | `├─` = conditional branch | `↻` = cycle detected

---

## The Problem

You open a new codebase. 200 files. Where do you start?

The file tree tells you nothing. Which functions matter? In what order do they execute? What triggers them?

You Cmd+Click through function calls. You grep. You read 10 files to understand 1 flow. Three days later you have a partial mental model that's already outdated.

**Code structure ≠ code story.** Files and classes are the architecture of the code. Flows and stories are the architecture of the system. CARTOGRAPH bridges the gap.

---

## What It Does

- **Scans** any codebase and discovers entry points — via framework detectors (FastAPI, Flask, Django, Celery) AND framework-agnostic topology discovery (works on any framework without configuration)
- **Builds** a global call graph with cross-file import resolution, parameter type inference, factory classmethod tracking, MRO walking, and return type inference
- **Traces** code flows from any function as a DAG with branch detection and async boundary marking
- **Renders** interactive DAGs in the browser — click, expand, search, zoom across your entire codebase
- **Exports** to JSON for downstream consumption (VS Code extension, CI pipelines)

---

## Quick Start

```bash
# Install
pip install cartograph-code

# Scan any Python project (first time parses everything, then cached)
carto scan /path/to/your/project

# Everything below uses the cache — instant, no path needed
carto entries                          # list all entry points
carto entries --type api_route         # filter by type
carto search "checkout"                # find functions by name
carto trace "CheckoutService.create"   # trace call tree
carto trace "send_webhook" --depth 5   # control depth
carto callers "UserService.create"     # who calls this?
carto summary                          # stats overview

# Pipe to any LLM — no API keys needed
carto context | claude "what does this codebase do"
carto context "deploy" | claude "explain the deploy flow"
carto context "checkout" | gh copilot explain

# Or use built-in LLM
export CARTOGRAPH_LLM_PROVIDER=claude   # or openai, ollama
export ANTHROPIC_API_KEY=sk-ant-...     # or OPENAI_API_KEY for openai
carto explain                          # explain whole codebase
carto explain "checkout"               # explain specific flow
```

---

## Web Viewer

Launch an interactive browser-based DAG explorer for any Python project:

```bash
# Launch the web viewer
carto serve /path/to/your/project --port 3333

# Open in browser: http://127.0.0.1:3333
```

**What happens:**
1. Parses all `.py` files in the target project (takes 1-3s for ~3000 functions)
2. Builds a global call graph with cross-file resolution
3. Starts a local web server
4. Open the browser — click entry points in the sidebar to render interactive DAGs

**Features:**
- Three-panel layout: sidebar (entry points) | DAG canvas (D3 + dagre) | detail panel (on click)
- Color-coded nodes: blue = API routes, purple = Celery tasks, amber = signal handlers
- Dashed edges = async dispatch, thick edges = cross-file calls
- Click node for details (file, line, decorators, callers/callees)
- Double-click node to re-root the graph at that function
- `[+]` button on leaf nodes to expand deeper
- Depth slider (1-8) to control how deep the trace goes
- Search across all functions with `/` keyboard shortcut
- Zoom and pan with mouse/trackpad

```bash
# Examples
carto serve ./polar/server --port 3333         # 600 entry points
carto serve ./sentry/src --port 3333           # 788 entry points
carto serve ./your-project --port 4000 --host 0.0.0.0
```

---

## Pipe to Any LLM

Cartograph outputs structured context that any LLM can consume. No API keys, no provider lock-in — pipe to whatever you already use.

```bash
# Codebase-level: "what is this project?"
carto context | claude "what does this codebase do"

# Scoped: "explain this specific flow"
carto context "deploy" | claude "explain the deploy flow step by step"

# Works with any LLM CLI
carto context "checkout" | gh copilot explain
carto context | llm "summarize the architecture"
```

**Token reduction:** Prefect's raw codebase is ~9M tokens. `carto context` outputs ~8K tokens — a **1,000x reduction** — while preserving every entry point, domain grouping, top callers, and package structure. The LLM gets the map, not the territory.

**Built-in LLM support** (optional — for `carto explain` without piping):

| Provider | Env Vars | Default Model |
|----------|----------|---------------|
| Claude | `ANTHROPIC_API_KEY` | claude-sonnet-4-20250514 |
| OpenAI | `OPENAI_API_KEY` | gpt-4o-mini |
| Ollama | `OLLAMA_HOST` (optional) | llama3.2 |

---

## Architecture

CARTOGRAPH is built as six decoupled layers:

```
┌────────────────┐
│  User Interface │  CLI (today) → VS Code Extension → Web UI
└───────┬────────┘
        ▼
┌────────────────┐
│   Core API      │  init / trace / summary / query / diff
└───────┬────────┘
        ▼
┌────────┬──────────┬──────────┐
│ Parse  │  Graph   │   LLM    │
│ Layer  │  Layer   │  Layer   │
└────────┴──────────┴──────────┘
```

| Layer | Job | Scales by |
|-------|-----|-----------|
| **Parse** | Extract functions, calls, decorators from source | Add language parsers as plugins (Python today, Java/Go/JS next) |
| **Graph** | Build call graph, resolve cross-file calls, construct flow DAGs | Universal — language-agnostic |
| **LLM** | Narrate flows from graph + source code | Pluggable providers — Claude, OpenAI, Ollama (or none) |
| **Cache** | Incremental re-analysis on file changes | File-hash based invalidation |
| **Render** | DAG → visual output | CLI / VS Code / Web / Mermaid / JSON |

**Key design decision:** The graph layer never changes when you add a new language or framework. Language parsers and framework detectors are plugins. Adding Java means writing `languages/java/adapter.py` + `languages/java/frameworks/spring_boot.py` — the graph engine, serializer, and CLI stay untouched.

Full HLD: [docs/hld.md](docs/hld.md) | Parser HLD: [docs/parser-hld.md](docs/parser-hld.md)

---

## Currently Supported

| Feature | Status |
|---------|--------|
| **Engine** | |
| Cross-file call resolution via import analysis | ✅ |
| Type-inferred method resolution (`x = Foo(); x.bar()`) | ✅ |
| Factory classmethod resolution (`x = Foo.create(); x.bar()`) | ✅ |
| Parameter type resolution (`def f(x: Foo): x.bar()`) | ✅ |
| Return type resolution (`x = get_foo(); x.bar()` where `get_foo() -> Foo`) | ✅ |
| `self.method()` resolution with MRO/inheritance walking | ✅ |
| Topology-based entry point discovery (framework-agnostic) | ✅ |
| Conditional branch detection | ✅ |
| Cycle detection | ✅ |
| **Language: Python** | |
| Python AST parsing | ✅ |
| Django Ninja route detection | ✅ |
| Celery task + async dispatch (`.delay()`, `chain`, `chord`, `group`) | ✅ |
| Django signal handler detection | ✅ |
| Django ORM operation annotation | ✅ |
| FastAPI route detection (`@app.get`, `@router.post`, `@app.websocket`) | ✅ |
| Flask route detection (`@app.route`, `@bp.get`, `@app.errorhandler`) | ✅ |
| **Interfaces** | |
| Interactive web viewer (`cartograph serve`) | ✅ |
| CLI with Rich tree output | ✅ |
| JSON export | ✅ |
| 122 unit tests + integration tests | ✅ |
| **LLM Narration** | |
| `cartograph explain` — AI-powered flow narration | ✅ |
| Claude, OpenAI, Ollama provider support | ✅ |
| Web viewer `/api/narrate/{qname}` endpoint | ✅ |
| **Planned** | |
| Diff mode ("what flows changed in this PR?") | 📋 Phase 2 |
| Tree-sitter migration (multi-language foundation) | 📋 Phase 3 |
| Java + Spring Boot | 📋 Phase 3 |
| Go + goroutine boundary detection | 📋 Phase 3 |
| TypeScript + Express/Nest | 📋 Phase 3 |
| VS Code extension | 📋 Phase 3 |

---

## Tested Against

| Project | Framework | Modules | Functions | Entry Points | Resolved Edges |
|---------|-----------|---------|-----------|-------------|----------------|
| **Sentry** | Django + Celery (custom) | 4,415 | 30,926 | 788 | 37,659 |
| **Polar** | FastAPI | 914 | 6,350 | 600 | 6,327 |
| **Prefect** | FastAPI + custom | 690 | 6,280 | 396 | 2,821 |
| **Dagster** | Custom framework | 790 | 11,533 | 255 | 6,919 |
| **paperless-ngx** | Django + Celery | 135 | 1,559 | 26 | 1,099 |

Sentry and Dagster use entirely custom decorator patterns — no Cartograph-specific detectors exist for them. Entry points discovered via graph topology.

122 unit tests passing.

---

## Roadmap

**Phase 1 (complete):** Python parser + call graph + type inference + CLI + web viewer
**Phase 2 (complete):** LLM narration + FastAPI/Flask detectors + principled type resolution + topology-based entry point discovery
**Phase 3:** Diff mode ("what flows changed in this PR?") + blast radius analysis
**Phase 4:** Multi-language via Tree-sitter (Java/Spring Boot, Go, TypeScript) + VS Code extension
**Phase 5:** CI integration, multi-repo linking, team features

---

## Why Not Just Ask an LLM?

You can ask Claude Code or Cursor to "trace the equipment pipeline." It will read some files, pattern-match, and give you a plausible answer. But:

- **LLMs sample. Cartograph enumerates.** An LLM reads files until it runs out of context. Cartograph parses every file, resolves every import, builds the complete graph. 30K functions in 3 seconds — exhaustive, not best-effort.
- **LLMs hallucinate edges. Cartograph proves them.** An LLM might say A calls B when it actually calls C. Cartograph resolves calls through the import chain — if it says A→B, that edge exists in the source.
- **LLMs need context. Cartograph provides it.** Instead of feeding 9M tokens of raw code to an LLM, pipe 8K tokens of structured context: `carto context | claude`. The LLM gets the map — every entry point, every domain, every flow — in one page.
- **LLMs forget. Cartograph is deterministic.** Same codebase, same graph, every time.

Cartograph builds the map. The LLM narrates it. They're complementary — `carto context | claude` gives your LLM grounded, exhaustive structural knowledge instead of best-effort file sampling.

## Comparison

| Tool | What it does | Where Cartograph differs |
|------|-------------|------------------------|
| VS Code Call Hierarchy | Shows callers/callees of one function | No cross-file DAG, no async detection, no branches |
| Sourcegraph | Code search and navigation | Finds code, doesn't map flows |
| Claude Code / Cursor | LLM reads files and explains | Probabilistic, partial. Cartograph is exhaustive and deterministic — then feeds the LLM |
| GraphRAG / text-to-graph | Compresses text into graph for LLM context | Cartograph parses actual code structure, not text. Edges are proven, not inferred |

---

## License

MIT

---

*LLMs guess. Cartograph proves.*
