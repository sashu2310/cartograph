# CARTOGRAPH

**Don't read the code. Read the story.**

CARTOGRAPH is an AI-powered code flow explorer that transforms codebases into interactive DAGs organized by user stories — not file structure.

```
cartograph init ./my-project

Discovered:
  142 modules | 1,847 functions | 509 entry points
  API Routes: 284 | Celery Tasks: 95 | Signal Handlers: 12 | Beat Schedules: 18
```

```
cartograph trace ./my-project "trigger_equipment_pipeline"

→ trigger_scheduled_equipment_pipeline()
  │ → get_facility_info_helper()
  │ → IngressQueue.objects.filter.order_by()
  │ ├─ if is_backfill_enabled
  │ │  → queue_types.append()
  │ ├─ if queue.type == INGESTION_PIPELINE
  │ │  ⚡ trigger_equipment_pipeline.apply_async()
  │ ├─ if queue.type == BACKFILL
  │ │  ⚡ trigger_equipment_pipeline.apply_async()
```

`→` = function call | `⚡` = async boundary (Celery) | `├─` = conditional branch | `↻` = cycle detected

---

## The Problem

You open a new codebase. 200 files. Where do you start?

The file tree tells you nothing. `diagnostics/tasks.py` has 24 functions — which ones matter? In what order do they execute? What triggers them?

You Cmd+Click through function calls. You grep. You read 10 files to understand 1 flow. Three days later you have a partial mental model that's already outdated.

**Code structure ≠ code story.** Files and classes are the architecture of the code. Flows and stories are the architecture of the system. CARTOGRAPH bridges the gap.

---

## What It Does

- **Scans** a codebase and discovers all entry points (API routes, Celery tasks, scheduled jobs, signal handlers)
- **Traces** code flows from any entry point as an interactive DAG with branch detection and async boundary marking
- **Detects** framework patterns — Django routes, Celery task dispatch (`.delay()`, `.apply_async()`, `chain`, `chord`, `group`), Django signals, ORM operations
- **Generates** user stories from code structure + documentation using LLM (optional)
- **Annotates** flows with human-readable descriptions using LLM (optional)

---

## Quick Start

```bash
# Clone
git clone https://github.com/sashu2310/cartograph.git
cd cartograph

# Install
pip install click rich

# Scan a codebase
python -m cartograph.cli init /path/to/your/project

# Trace a specific function
python -m cartograph.cli trace /path/to/your/project "function_name"

# Trace with JSON output
python -m cartograph.cli trace /path/to/your/project "function_name" -o flow.json
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
│   Core API      │  init / trace / list / query / diff
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
| **Graph** | Build call graph, construct flow DAGs | Universal — language-agnostic |
| **LLM** | Generate stories, annotate flows, answer queries | Swap providers (Claude, GPT, Ollama, or none) |
| **Cache** | Incremental re-analysis on file changes | File-hash based invalidation |
| **Render** | DAG → visual output | CLI / VS Code / Web / Mermaid / JSON |
| **Provider** | LLM backend abstraction | Protocol-based, pluggable |

**Key design decision:** The graph layer never changes when you add a new language or framework. Language parsers and framework detectors are plugins. Adding Java support means writing `languages/java.py` + `frameworks/spring_boot.py` — the graph engine, serializer, and CLI stay untouched.

Full HLD: [docs/hld.md](docs/hld.md)

---

## Currently Supported

| Feature | Status |
|---------|--------|
| Python AST parsing | ✅ |
| Django Ninja route detection | ✅ |
| Celery task detection | ✅ |
| Celery async dispatch (`.delay()`, `.apply_async()`) | ✅ |
| Celery orchestration (`chain`, `chord`, `group`) | ✅ |
| Django signal handler detection | ✅ |
| Conditional branch detection | ✅ |
| Cycle detection | ✅ |
| CLI with Rich output | ✅ |
| JSON export | ✅ |
| Cross-file call resolution | 🔨 In progress |
| LLM story generation | 📋 Phase 2 |
| LLM flow annotation | 📋 Phase 2 |
| VS Code extension | 📋 Phase 2 |
| Java / Go / JS support | 📋 Phase 4 |

---

## Roadmap

**Phase 1 (current):** Core parser + call graph + CLI
**Phase 2:** LLM integration + VS Code extension with interactive DAG
**Phase 3:** Natural language queries, diff mode, filters
**Phase 4:** Multi-language support via Tree-sitter (Java, Go, JS)
**Phase 5:** Multi-repo linking, web UI, team features

---

## Why Not...

| Tool | What it does | Where CARTOGRAPH differs |
|------|-------------|------------------------|
| VS Code Call Hierarchy | Shows callers/callees of one function | No story context, no DAG, no async detection |
| Sourcegraph | Code search and navigation | Finds code, doesn't explain flows |
| CodeSee (dead) | Runtime code flow visualization | Required instrumentation. CARTOGRAPH is static — no setup |
| GitHub Copilot | Explains code snippets | Point explanations, not system-level flows |

---

## License

MIT

---

*The art of making maps for uncharted codebases.*
