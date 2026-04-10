# CARTOGRAPH

**Don't read the code. Read the story.**

CARTOGRAPH is an AI-powered code flow explorer that maps any codebase into interactive DAGs — tracing every call chain across files, detecting async boundaries, narrating what each flow does, and rendering the result in your browser. Language-agnostic engine, pluggable framework detectors. Python shipped, more languages next.

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
| **Interfaces** | |
| Interactive web viewer (`cartograph serve`) | ✅ |
| CLI with Rich tree output | ✅ |
| JSON export | ✅ |
| 96 unit tests + integration tests | ✅ |
| **Planned** | |
| LLM flow narration ("what does this flow do?") | 📋 Phase 2 |
| FastAPI / Flask route detection | 📋 Phase 2 |
| Tree-sitter migration (multi-language foundation) | 📋 Phase 3 |
| Java + Spring Boot | 📋 Phase 3 |
| Go + goroutine boundary detection | 📋 Phase 3 |
| TypeScript + Express/Nest | 📋 Phase 3 |
| VS Code extension | 📋 Phase 3 |

---

## Tested Against

| Project | Type | Modules | Functions | Resolved Edges | Entry Points | Deepest DAG |
|---------|------|---------|-----------|----------------|-------------|-------------|
| **paperless-ngx** | Application (Django+Celery) | 135 | 1,559 | 1,099 | 26 | 49 nodes / 12 files |
| **Celery** | Framework | 161 | 3,086 | 1,846 | 1 | 30 nodes / 8 files |
| **Kombu** | Library | 78 | 1,646 | 198 | 0 | — |
| **Prefect** | Framework | 1,000+ | 10,000+ | — | — | — |

**Best results on application codebases** with layered architecture (controller → service → task). Framework/library code has lower resolution due to dynamic dispatch and inheritance patterns — a known boundary of static analysis.

96 tests passing across all projects.

---

## Roadmap

**Phase 1 (complete):** Python parser + call graph + type inference + CLI + web viewer
**Phase 2:** LLM flow narration + more framework detectors (FastAPI, Flask)
**Phase 3:** Multi-language via Tree-sitter (Java, Go, TypeScript) + VS Code extension
**Phase 4:** Diff mode ("what flows changed in this PR?"), CI integration
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
