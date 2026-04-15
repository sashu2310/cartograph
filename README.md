# CARTOGRAPH

**Don't read the code. Read the story.**

CARTOGRAPH is an AI-powered code flow explorer that maps any codebase into interactive DAGs — tracing every call chain across files, detecting async boundaries, narrating what each flow does, and rendering the result in your browser. Language-agnostic engine, pluggable framework detectors. Python shipped, more languages next.

---

## Real Output — Parsing Open Source Projects

### Polar (FastAPI — billing/subscriptions platform)

```
$ cartograph summary ./polar/server

Modules:        914
Functions:      6,350
Entry points:   328
Resolved calls: 5,572
Unresolved:     23,441

Top callers (most outgoing calls):
   59  scripts.seeds_load.create_seed_data
   43  polar.backoffice.organizations_v2.endpoints.get_organization_detail
   33  polar.checkout.service.CheckoutService.create
```

```
$ cartograph trace ./polar/server "get_claim_info" --depth 2

Found: polar.customer_seat.endpoints.get_claim_info
File: polar/customer_seat/endpoints.py:323
Decorators: router.get
Outgoing calls: 6 (6 cross-file, 0 async)

get_claim_info polar/customer_seat/endpoints.py:323
├── → SeatService.get_seat_by_token polar/customer_seat/service.py
│   ├── ├─ if not seat or seat.is_revoked() or seat.is_claimed()
│   └── ├─ if seat.invitation_token_expires_at and seat.invitation_token_e...
├── → SeatService.check_seat_feature_enabled polar/customer_seat/service.py
│   ├── → FeatureNotEnabled
│   ├── ├─ if not organization
│   │   └── → FeatureNotEnabled
│   └── ├─ if not organization.feature_settings.get('seat_based_pricing_en...
│       └── → FeatureNotEnabled
├── → SeatClaimInfo polar/customer_seat/schemas.py
├── → ResourceNotFound server/polar/exceptions.py
├── ├─ if not seat
│   └── → ResourceNotFound
├── ├─ if seat.subscription
├── ├─ else
│   └── → ResourceNotFound
├── ├─ if not organization
│   └── → ResourceNotFound
├── ├─ if seat.email
├── ├─ if seat.member
└── ├─ else

Reachable: 5 functions across 4 files
```

### paperless-ngx (Django + Celery — document management)

```
$ cartograph summary ./paperless-ngx/src

Modules:        135
Functions:      1,559
Entry points:   26 (Celery tasks, signal handlers, API routes)
Resolved calls: 1,099
```

```
$ cartograph trace ./paperless-ngx/src "send_webhook" --depth 3

Found: documents.workflows.webhooks.send_webhook
File: documents/workflows/webhooks.py:77
Decorators: shared_task
Outgoing calls: 2 (1 cross-file, 0 async)

send_webhook documents/workflows/webhooks.py:77
├── → validate_outbound_http_url paperless/network.py
│   ├── → resolve_hostname_ips
│   │   └── ├─ if not ips
│   │       └── → ValueError()
│   ├── → is_public_ip
│   ├── ├─ if scheme not in allowed_schemes or not parsed.hostname
│   │   └── → ValueError()
│   ├── ├─ if allowed_ports and port not in allowed_ports
│   │   └── → ValueError()
│   ├── ├─ if not is_public_ip(ip_str)
│   │   └── → ValueError()
│   └── ├─ if not allow_internal
│       ├── → resolve_hostname_ips
│       └── → is_public_ip
├── → WebhookTransport
├── ├─ if hostname is None
│   └── → ValueError()
├── ├─ if as_json
└── ├─ else

Reachable: 5 functions across 2 files
```

### Redash (Flask — data visualization)

```
$ cartograph summary ./redash/redash

Modules:        168
Functions:      1,691
Entry points:   24
Resolved calls: 635
```

CARTOGRAPH works best on **application codebases** with layered architecture (controller → service → task → model). Resolution is highest on codebases that use explicit service imports (like Polar's `from .service import user_service` pattern). Framework/library code with heavy dynamic dispatch produces lower resolution — a known boundary of static analysis.

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

- **Scans** any codebase and discovers entry points (API routes, async tasks, signal handlers — via pluggable framework detectors)
- **Builds** a global call graph with cross-file import resolution and type-inferred method resolution
- **Traces** code flows from any function as a DAG with branch detection and async boundary marking
- **Renders** interactive DAGs in the browser — click, expand, search, zoom across your entire codebase
- **Exports** to JSON for downstream consumption (VS Code extension, CI pipelines)

---

## Quick Start

```bash
# Clone
git clone https://github.com/sashu2310/cartograph.git
cd cartograph

# Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Scan a codebase
python -m cartograph.cli init /path/to/your/project

# Summary with call graph stats
python -m cartograph.cli summary /path/to/your/project

# Trace a specific function
python -m cartograph.cli trace /path/to/your/project "function_name"

# Trace with JSON output
python -m cartograph.cli trace /path/to/your/project "function_name" -o flow.json

# Control depth
python -m cartograph.cli trace /path/to/your/project "function_name" --depth 5

# AI-powered flow narration
export CARTOGRAPH_LLM_PROVIDER=claude  # or openai, ollama
export ANTHROPIC_API_KEY=sk-...        # or OPENAI_API_KEY
python -m cartograph.cli explain /path/to/your/project "function_name"
```

---

## Web Viewer

Launch an interactive browser-based DAG explorer for any Python project:

```bash
# Make sure you're in the cartograph directory with venv active
cd cartograph
source .venv/bin/activate

# Launch the web viewer against any Python project
python -m cartograph.cli serve /path/to/your/project --port 3333

# Open in browser
# http://127.0.0.1:3333
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
python -m cartograph.cli serve ./polar/server --port 3333        # 328 FastAPI routes
python -m cartograph.cli serve ./paperless-ngx/src --port 3333   # Django + Celery
python -m cartograph.cli serve ./your-project/src --port 4000 --host 0.0.0.0
```

---

## LLM Flow Narration

Ask "what does this flow do?" and get an AI-generated narrative of the call chain — grounded in the actual graph and source code, not hallucinated.

```bash
# Set provider (claude, openai, or ollama)
export CARTOGRAPH_LLM_PROVIDER=claude
export ANTHROPIC_API_KEY=sk-ant-...

# Narrate a flow from the CLI
cartograph explain /path/to/project "consume_file" --depth 3

# Or use the web viewer — click any node and hit "Narrate"
cartograph serve /path/to/project
# GET /api/narrate/{qualified_name}?depth=5
```

**Supported providers:**

| Provider | Env Vars | Default Model |
|----------|----------|---------------|
| Claude | `ANTHROPIC_API_KEY` | claude-sonnet-4-20250514 |
| OpenAI | `OPENAI_API_KEY` | gpt-4o-mini |
| Ollama | `OLLAMA_HOST` (optional) | llama3.2 |

Override the model with `CARTOGRAPH_LLM_MODEL`. All providers use the same narration pipeline: serialize subgraph → extract source snippets for key functions → build prompt → generate narrative.

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
| `self.method()` resolution within classes | ✅ |
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
| 114 unit tests + integration tests | ✅ |
| **LLM Narration** | |
| `cartograph explain` — AI-powered flow narration | ✅ |
| Claude, OpenAI, Ollama provider support | ✅ |
| Web viewer `/api/narrate/{qname}` endpoint | ✅ |
| **Planned** | |
| Polymorphic dispatch via type hints + subclass expansion | 📋 Phase 2 |
| Diff mode ("what flows changed in this PR?") | 📋 Phase 2 |
| Tree-sitter migration (multi-language foundation) | 📋 Phase 3 |
| Java + Spring Boot | 📋 Phase 3 |
| Go + goroutine boundary detection | 📋 Phase 3 |
| TypeScript + Express/Nest | 📋 Phase 3 |
| VS Code extension | 📋 Phase 3 |

---

## Tested Against

| Project | Framework | Modules | Functions | Resolved Edges | Entry Points |
|---------|-----------|---------|-----------|----------------|--------------|
| **Polar** | FastAPI | 914 | 6,350 | 5,572 | 328 |
| **paperless-ngx** | Django + Celery | 135 | 1,559 | 1,099 | 26 |
| **Redash** | Flask | 168 | 1,691 | 635 | 24 |

122 unit tests passing.

---

## Roadmap

**Phase 1 (complete):** Python parser + call graph + type inference + CLI + web viewer
**Phase 2 (in progress):** ~~LLM flow narration~~ ✅ + ~~FastAPI/Flask detectors~~ ✅ + polymorphic dispatch + diff mode
**Phase 3:** Multi-language via Tree-sitter (Java, Go, TypeScript) + VS Code extension
**Phase 4:** CI integration, PR flow impact analysis
**Phase 5:** Multi-repo linking, team features

---

## Why Not Just Ask an LLM?

You can ask Claude Code or Cursor to "trace the equipment pipeline." It will read some files, pattern-match, and give you a plausible answer. But:

- **LLMs sample. CARTOGRAPH enumerates.** An LLM reads files until it runs out of context. CARTOGRAPH parses every file, resolves every import, builds the complete graph. 3000 functions in 2 seconds — exhaustive, not best-effort.
- **LLMs hallucinate edges. CARTOGRAPH proves them.** An LLM might say A calls B when it actually calls C. CARTOGRAPH resolves calls through the import chain — if it says A→B, that edge exists in the source.
- **LLMs produce text. CARTOGRAPH produces structure.** A JSON graph with nodes and edges feeds into VS Code extensions, CI pipelines, diff tools. Prose doesn't.
- **LLMs forget. CARTOGRAPH is deterministic.** Same codebase, same graph, every time.

CARTOGRAPH builds the map. The LLM narrates it. They're complementary — the exhaustive structural graph is what makes AI narration trustworthy instead of guesswork.

## Comparison

| Tool | What it does | Where CARTOGRAPH differs |
|------|-------------|------------------------|
| VS Code Call Hierarchy | Shows callers/callees of one function | No cross-file DAG, no async detection, no branches |
| Sourcegraph | Code search and navigation | Finds code, doesn't explain flows |
| CodeSee (dead) | Runtime code flow visualization | Required instrumentation. CARTOGRAPH is static — no setup |
| Claude Code / Cursor | LLM reads files and explains | Probabilistic, partial, no structured output. CARTOGRAPH is exhaustive and deterministic |

---

## License

MIT

---

*The art of making maps for uncharted codebases.*
