# CARTOGRAPH

**Don't read the code. Read the story.**

CARTOGRAPH is an AI-powered code flow explorer that transforms codebases into interactive DAGs organized by user stories — not file structure.

---

## Real Output — Parsing Open Source Projects

### Celery (10M+ monthly downloads)

```
$ cartograph summary ./celery

Modules:        161
Functions:      3111
Entry points:   1
Resolved calls: 665
Unresolved:     8287

Unresolved breakdown:
  not_in_project: 5178
  builtin: 1690
  builtin_method: 1235
  logging: 184

Top callers (most outgoing calls):
   16  app.trace.build_tracer
    8  utils.saferepr.reprstream
    7  apps.multi.Cluster.shutdown_nodes
    6  bin.base.CeleryDaemonCommand.__init__
    6  contrib.migrate.move
```

### Tracing Celery's Task Tracer — Cross-File Resolution

```
$ cartograph trace ./celery "build_tracer" --depth 3

Found: app.trace.build_tracer
File: celery/app/trace.py:320
Outgoing calls: 16 (1 cross-file, 1 async)

build_tracer celery/app/trace.py:320
├── → task_has_custom
├── → traceback_clear
│   ├── ├─ if hasattr(exc, '__traceback__')
│   ├── ├─ else
│   │   └── → sys.exc_info() (unresolved)
│   └── ├─ if exc is not None
│       └── → hasattr() (unresolved)
├── → _signal_internal_error
│   ├── → traceback_clear
│   └── ├─ if einfo is not None
│       └── → traceback_clear
├── → report_internal_error
├── ⚡ group.apply_async (celery_apply_async) celery/canvas.py     ← cross-file
│   ├── ├─ if app.conf.task_always_eager
│   │   └── → self.apply() (unresolved)
│   ├── ├─ if not self.tasks
│   │   └── → self.freeze() (unresolved)
│   └── ├─ if add_to_parent and parent_task
│       └── → parent_task.add_trail() (unresolved)
├── ├─ if task_has_custom(task, 'on_success')
├── ├─ if prerun_receivers
│   └── → send_prerun() (unresolved)
├── ├─ if sigs
│   └── ⚡ group.apply_async
├── ├─ if task_on_success
│   └── → task_on_success() (unresolved)
├── ├─ if not eager
│   └── → task.backend.process_cleanup() (unresolved)
...

Reachable: 8 functions across 2 files
```

### Kombu — Tracing the QoS Memory Leak Fix

```
$ cartograph trace ./kombu "QoS.increment_eventually"

Found: common.QoS.increment_eventually
File: kombu/common.py:408

QoS.increment_eventually kombu/common.py:408
├── ├─ if self.max_prefetch is not None and new_value > self.max_prefe...
└── ├─ if self.value
    └── → max() (unresolved)

Reachable: 1 functions across 1 files
```

The `max_prefetch` guard visible in the trace is from [Kombu PR #2348](https://github.com/celery/kombu/pull/2348) — a fix for unbounded memory growth in Celery's ETA task queue.

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

- **Scans** a codebase and discovers all entry points (API routes, Celery tasks, scheduled jobs, signal handlers)
- **Builds** a global call graph with cross-file import resolution
- **Traces** code flows from any function as a DAG with branch detection and async boundary marking
- **Detects** framework patterns — Django routes, Celery task dispatch (`.delay()`, `.apply_async()`, `chain`, `chord`, `group`), Django signals, ORM operations
- **Exports** to JSON for downstream consumption (VS Code extension, web UI)

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
python -m cartograph.cli serve ./celery/celery --port 3333
python -m cartograph.cli serve ./django/django --port 3333
python -m cartograph.cli serve ./your-project/src --port 4000 --host 0.0.0.0
```

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
| **LLM** | Generate stories, annotate flows, answer queries | Swap providers (Claude, GPT, Ollama, or none) |
| **Cache** | Incremental re-analysis on file changes | File-hash based invalidation |
| **Render** | DAG → visual output | CLI / VS Code / Web / Mermaid / JSON |
| **Provider** | LLM backend abstraction | Protocol-based, pluggable |

**Key design decision:** The graph layer never changes when you add a new language or framework. Language parsers and framework detectors are plugins. Adding Java means writing `languages/java/adapter.py` + `languages/java/frameworks/spring_boot.py` — the graph engine, serializer, and CLI stay untouched.

Full HLD: [docs/hld.md](docs/hld.md) | Parser HLD: [docs/parser-hld.md](docs/parser-hld.md)

---

## Currently Supported

| Feature | Status |
|---------|--------|
| Python AST parsing | ✅ |
| Cross-file call resolution via import analysis | ✅ |
| Django Ninja route detection | ✅ |
| Celery task detection | ✅ |
| Celery async dispatch (`.delay()`, `.apply_async()`) | ✅ |
| Celery orchestration (`chain`, `chord`, `group`) | ✅ |
| Django signal handler detection | ✅ |
| Django ORM operation annotation | ✅ |
| Conditional branch detection | ✅ |
| Cycle detection | ✅ |
| CLI with Rich tree output | ✅ |
| JSON export | ✅ |
| Project summary with call graph stats | ✅ |
| Interactive web viewer (`cartograph serve`) | ✅ |
| 96 unit tests + integration tests | ✅ |
| LLM story generation | 📋 Phase 2 |
| LLM flow annotation | 📋 Phase 2 |
| VS Code extension | 📋 Phase 3 |
| Java / Go / JS support | 📋 Phase 4 |

---

## Tested Against

| Project | Modules | Functions | Resolved Calls | Entry Points |
|---------|---------|-----------|----------------|-------------|
| **Celery** | 161 | 3,111 | 665 | 1 |
| **Kombu** | 78 | 1,646 | 198 | 0 |
| **Prefect** | 1,000+ | 10,000+ | — | — |

All parsed without crashes. 86 unit tests + 10 integration tests passing.

---

## Roadmap

**Phase 1 (current):** Core parser + call graph + CLI + JSON export
**Phase 2:** LLM integration + VS Code extension with interactive DAG
**Phase 3:** Natural language queries, diff mode, filters
**Phase 4:** Multi-language support via Tree-sitter (Java, Go, JS)
**Phase 5:** Multi-repo linking, web UI, team features

---

## Why Not...

| Tool | What it does | Where CARTOGRAPH differs |
|------|-------------|------------------------|
| VS Code Call Hierarchy | Shows callers/callees of one function | No cross-file DAG, no async detection, no branches |
| Sourcegraph | Code search and navigation | Finds code, doesn't explain flows |
| CodeSee (dead) | Runtime code flow visualization | Required instrumentation. CARTOGRAPH is static — no setup |
| GitHub Copilot | Explains code snippets | Point explanations, not system-level flows |

---

## License

MIT

---

*The art of making maps for uncharted codebases.*
