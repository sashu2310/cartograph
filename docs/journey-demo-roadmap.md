# CARTOGRAPH — Journey, Demo Script, and Roadmap

## Part 1: The Journey So Far

### Timeline

**April 4, 2026** — Day 1: Idea to working tool in one session
- Started from "LLM-enabled static code parsing" concept
- Built the core AST parser, graph models, CLI, and HLD
- Designed three-layer parser architecture (syntax → language adapter → framework detector)
- Added unit tests, integration tests, linting, pre-commit hooks
- Built call graph builder with cross-file import resolution
- Rewired CLI to use call graph for trace and summary
- Tested against Celery (161 modules, 3111 functions), Kombu (78 modules), Prefect (1000+ modules)
- Published to GitHub: github.com/sashu2310/cartograph

**April 10, 2026** — Day 2: Interactive web viewer
- Extracted `core.py` (shared pipeline for CLI + web)
- Built FastAPI web server with 5 API endpoints
- Built D3.js + dagre browser-based DAG explorer (865 lines of HTML/CSS/JS)
- Dark theme, three-panel layout, expand-on-demand, depth slider, search
- Tested against turbomechanica-server (270 modules, 3385 functions) — full DAGs rendered

### By the Numbers

| Metric | Count |
|--------|-------|
| Commits | 9 |
| Python source files | 25 |
| Python LOC | 3,453 |
| HTML/CSS/JS LOC | 865 |
| Test files | 8 |
| Tests passing | 96 |
| Framework detectors | 4 (Celery, Django Ninja, Django ORM, Django Signals) |
| Codebases tested | 3 open source (Celery, Kombu, Prefect) + 1 production (turbomechanica) |
| Total lines changed | 5,073 |

### What Exists Today

```
PARSE (Python AST) → CALL GRAPH (cross-file resolution) → RENDER (CLI + Web)
```

1. **Three-layer parser** — LanguageAdapter + FrameworkDetector + Registry pattern
   - PythonAdapter: extracts functions, calls, branches, decorators, imports
   - 4 framework detectors: Celery, Django Ninja, Django ORM, Django Signals
   - Adding a new language = 1 adapter file + N detector files. Graph layer untouched.

2. **Call graph builder** — global function registry + import index + edge resolution
   - Cross-file calls via import analysis
   - Async boundary detection (.delay(), .apply_async(), chain, chord, group)
   - Unresolved call classification (builtin, builtin_method, logging, not_in_project)

3. **CLI** — `init`, `trace`, `summary`, `serve`
   - Rich tree output with cross-file labels, async markers, branch conditions
   - JSON export for downstream tooling
   - Web viewer launch

4. **Web viewer** — `cartograph serve ./project --port 3333`
   - FastAPI serving D3.js + dagre interactive DAGs
   - Sidebar with entry points grouped by type
   - Click → DAG canvas, detail panel with file/line/decorators/callers
   - Expand-on-demand, depth slider, search, zoom/pan, re-root

---

## Part 2: Demo Script — Jensen Style

### Philosophy

Jensen doesn't demo features. He tells a story about a problem everyone has, builds tension, then reveals the solution live. The demo must feel like a magic trick — not a product walkthrough.

### Script: "You Don't Know Your Own Codebase"

**[Opening — The Problem] (60 seconds)**

"Every developer has had this moment. You join a new team. You open the repo. 200 files. 3000 functions. You Cmd+Click through imports. You grep. You read 10 files to understand 1 flow. Three days later, you have a partial mental model — that's already wrong.

Here's the thing. The file tree tells you the architecture of the *code*. But you don't ship code. You ship *flows*. What happens when a user hits that API? What fires when the sensor data arrives? Where does the Celery task fan out? That's the system. And no tool shows you that.

Until now."

**[The Reveal — Live Demo] (3 minutes)**

"Let me show you. This is Celery. The most popular distributed task queue in Python. 161 modules. 3,111 functions. Nobody new to this codebase has any idea where to start."

*Terminal:*
```
cartograph serve ./celery --port 3333
```

"One command. One second to parse. Open the browser."

*Browser opens. Dark UI. Sidebar with entry points.*

"On the left — every entry point. API routes. Celery tasks. Signal handlers. CARTOGRAPH found them automatically by reading the decorators.

Let me click on `build_tracer` — this is the function that executes every single Celery task in production."

*DAG renders. 8 nodes. Async boundaries visible.*

"See that dashed purple line? That's an async boundary — a `.apply_async()` call. The function is dispatching work to another process. CARTOGRAPH detected it automatically.

See that yellow edge? Cross-file call. `trace.py` calling into `canvas.py`. CARTOGRAPH resolved this through the import chain — no runtime instrumentation, pure static analysis.

Now I click this node..."

*Detail panel opens. File, line number, decorators, docstring, callers.*

"File path, line number, every decorator, who calls this function, what this function calls. Click any caller — the graph re-roots. You're navigating the codebase the way it actually executes."

*Increases depth slider from 3 to 6. Graph expands.*

"Depth slider. Go deeper into the call chain. The graph expands in real time."

*Clicks [+] on a leaf node. Subgraph merges in.*

"And when you see a `+` — that means there's more. Click it. The subgraph loads and merges in. You're exploring the codebase like a map. Not reading it like a book."

**[The Architecture — Why It's Different] (60 seconds)**

"Here's why this isn't just another code viz tool.

CARTOGRAPH doesn't run your code. No instrumentation. No tracing. No dependencies to install in your project. It reads the AST, resolves imports across files, detects framework patterns — Celery tasks, Django routes, ORM operations — and builds a global call graph.

The parser is pluggable. Three layers: syntax parsing, language adapter, framework detector. Adding Java means writing one adapter file. The graph engine never changes. M languages + N frameworks = M + N files, not M times N.

We tested it against Celery, Kombu, Prefect — 1000+ module codebases. Parses without crashing. 96 tests passing."

**[Close — The Vision] (30 seconds)**

"Today CARTOGRAPH shows you the graph. Tomorrow it tells you the story. We're adding an LLM layer that narrates what each flow does in plain English. Ask 'what happens when a sensor triggers an alert?' and get a walkthrough — not grep results.

The codebase is a map. Most tools give you a flashlight. CARTOGRAPH gives you the whole atlas."

### Demo Logistics

- **Duration:** 5 minutes max
- **Props needed:** Terminal + browser side-by-side
- **Target project for demo:** Celery (recognizable, open source, complex enough)
- **Fallback:** Pre-recorded GIF if live demo fails (never trust live demos, Jensen would agree)
- **Key moments to nail:**
  1. The one-command parse (speed)
  2. The first DAG render (visual impact)
  3. The async boundary detection (intelligence)
  4. The expand-on-demand (interactivity)
  5. The depth slider (control)

---

## Part 3: Roadmap Forward

### Phase 1.5: Polish for Launch (Next 3-4 days → April 14)

**Goal:** HN-ready. The web viewer works, but it needs to feel polished.

1. **Node color by entry point type** — Right now nodes are colored by function type (method, function). They should also reflect if a function IS an entry point. The root node of a Celery task should be purple, not slate.

2. **Entry point auto-detection coverage** — Celery only shows 1 entry point (`ping`) because most tasks in Celery's own codebase don't use `@shared_task`. Add detection for `app.task()` in more patterns. Flask/FastAPI route detection (new detector).

3. **Full graph overview mode** — A minimap or "all entry points" view that shows the project topology (islands, bridges, orphans) without picking a single function. This is the "wow" screenshot for HN.

4. **Performance for large graphs** — Depth 8 on a 3000-function codebase could produce 100+ node subgraphs. Add client-side node limit (collapse beyond N nodes), progressive rendering.

5. **Smooth transitions** — D3 enter/exit/update animations when expanding/collapsing/re-rooting. Currently the graph snaps — it should animate.

6. **README GIF** — Record a 20-second GIF of the web viewer in action. This is the #1 thing that gets HN clicks.

7. **`pip install cartograph`** — Publish to PyPI so people can try it without cloning.

### Phase 2: LLM Layer (April 15-25)

**Goal:** "What does this flow do?" in plain English.

1. **Flow narrative generation** — Feed a subgraph JSON to Claude/GPT and get a 2-paragraph explanation of what the flow does, what data it transforms, and where it dispatches work.

2. **Node annotation** — LLM adds one-line summaries to each node: "Validates sensor data and dispatches to physics engine."

3. **Natural language query** — "What happens when equipment pipeline runs?" → identifies the entry point, traces the graph, narrates the flow.

4. **Provider abstraction** — Protocol-based LLM adapter (Claude, OpenAI, Ollama, none). Same pattern used in VENN.

### Phase 3: VS Code Extension (May)

**Goal:** DAG visualization inside the editor.

1. **Webview panel** — Same D3+dagre rendering, embedded in VS Code.
2. **Click-to-navigate** — Click a node → opens the file at that line in the editor.
3. **Auto-detect entry point** — If cursor is inside a `@route` or `@shared_task`, show its DAG automatically.
4. **CodeLens** — Inline "View flow" link above entry point functions.

### Phase 4: Multi-Language (June+)

**Goal:** Java, Go, TypeScript support.

1. **Tree-sitter migration** — Replace stdlib `ast` with Tree-sitter for language-agnostic parsing.
2. **Java adapter** — Spring Boot controller detection, `@Async`, `@Scheduled`.
3. **Go adapter** — goroutine detection, channel boundaries, HTTP handler detection.
4. **TypeScript adapter** — Express/Nest route detection, async/await boundaries.

### Phase 5: Community & Scale

1. **Multi-repo linking** — Trace flows across microservices.
2. **Diff mode** — "What flows changed in this PR?"
3. **CI integration** — Auto-generate flow docs on every merge.
4. **Team features** — Shared annotations, bookmarked flows.

---

## Key Dates

| Date | Milestone |
|------|-----------|
| April 4 | Project created, Phase 1 complete |
| April 10 | Web viewer shipped |
| ~April 14 | HN launch (needs GIF, PyPI, polish) |
| ~April 25 | LLM layer MVP |
| ~May 15 | VS Code extension alpha |
| ~June | Multi-language support begins |

## What Makes CARTOGRAPH Different

Three things no other tool does:

1. **Async boundary detection** — .delay(), .apply_async(), chain, chord, group. No other static analysis tool marks where synchronous execution hands off to distributed workers. This is what makes Celery/Django codebases actually understandable.

2. **Pluggable framework detection** — The graph engine is language-agnostic. Framework patterns are plugins. Adding Spring Boot doesn't require changing the core. This is the M+N vs M×N insight.

3. **Interactive subgraph exploration** — Not a hairball of 3000 nodes. Depth-limited, expand-on-demand, re-rootable. You explore the codebase the way you think about it — one flow at a time.
