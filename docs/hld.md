# CARTOGRAPH — High Level Design

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER INTERFACES                               │
│                                                                      │
│   ┌──────────┐    ┌──────────────┐    ┌───────────────────────┐     │
│   │   CLI    │    │  VS Code     │    │   Web UI (Future)     │     │
│   │  (Click) │    │  Extension   │    │   (Standalone SaaS)   │     │
│   └────┬─────┘    └──────┬───────┘    └───────────┬───────────┘     │
│        │                 │                         │                  │
└────────┼─────────────────┼─────────────────────────┼─────────────────┘
         │                 │                         │
         ▼                 ▼                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      CARTOGRAPH CORE API                             │
│                                                                      │
│   Exposes: init / trace / list / query / diff                        │
│   Protocol: In-process (CLI) | HTTP (VS Code, Web) | LSP (Future)   │
│                                                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                 ▼
┌──────────────────┐ ┌─────────────────┐ ┌──────────────────┐
│   PARSE LAYER    │ │   GRAPH LAYER   │ │    LLM LAYER     │
│                  │ │                 │ │                  │
│  "What exists    │ │ "How things     │ │ "What it means   │
│   in the code?"  │ │  connect"       │ │  to a human"     │
│                  │ │                 │ │                  │
└────────┬─────────┘ └────────┬────────┘ └────────┬─────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌──────────────────┐ ┌─────────────────┐ ┌──────────────────┐
│   CACHE LAYER    │ │   RENDER LAYER  │ │  PROVIDER LAYER  │
│                  │ │   (DAG → Visual)│ │  (LLM Providers) │
│  ".cartograph/"  │ │                 │ │                  │
└──────────────────┘ └─────────────────┘ └──────────────────┘
```

---

## Component Breakdown

### 1. Parse Layer — "What exists in the code?"

This layer's only job: take source code files → produce structured data about what's in them. It knows nothing about flows, stories, or graphs.

```
┌─────────────────────────────────────────────────────────┐
│                     PARSE LAYER                          │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Language Parsers                     │    │
│  │         (One per programming language)            │    │
│  │                                                   │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐         │    │
│  │  │  Python  │ │   Java   │ │    Go    │  ...    │    │
│  │  │ (stdlib  │ │ (tree-   │ │ (tree-   │         │    │
│  │  │   ast)   │ │  sitter) │ │  sitter) │         │    │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘         │    │
│  │       │             │            │                │    │
│  │       ▼             ▼            ▼                │    │
│  │  ┌──────────────────────────────────────────┐    │    │
│  │  │         ParsedModule (Uniform Output)     │    │    │
│  │  │  - functions, classes, imports, calls      │    │    │
│  │  └──────────────────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │           Framework Detectors                     │    │
│  │      (Pluggable, per framework per language)      │    │
│  │                                                   │    │
│  │  ┌────────────┐ ┌────────┐ ┌─────────┐          │    │
│  │  │Django Ninja│ │Celery  │ │ Spring  │  ...     │    │
│  │  │            │ │        │ │  Boot   │          │    │
│  │  └────────────┘ └────────┘ └─────────┘          │    │
│  │                                                   │    │
│  │  Input:  ParsedModule (decorators, calls, etc)   │    │
│  │  Output: EntryPoints, AsyncBoundaries, ORM ops   │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │           Module Resolver                         │    │
│  │                                                   │    │
│  │  "from diagnostics.tasks import process_test"    │    │
│  │       → server/diagnostics/tasks.py              │    │
│  │                                                   │    │
│  │  Resolves: absolute imports, relative imports,   │    │
│  │            sys.path modifications, __init__.py   │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**Abstraction contract:**
```python
class LanguageParser(Protocol):
    def parse(self, source: str, file_path: str) -> ParsedModule

class FrameworkDetector(Protocol):
    def detect_entry_points(self, module: ParsedModule) -> list[EntryPoint]
    def detect_async_boundaries(self, call: FunctionCall) -> Optional[AsyncBoundary]
    def annotate_operations(self, call: FunctionCall) -> Optional[OperationAnnotation]
```

**Scaling concern:** New language = new `LanguageParser` implementation. New framework = new `FrameworkDetector`. Neither changes the graph or LLM layers. This is the key abstraction boundary.

**Potential blocker:** Module resolution across large monorepos with complex `sys.path` manipulation, namespace packages, and dynamic imports. Mitigation: best-effort resolution with unresolved calls marked as `EXTERNAL_CALL` nodes rather than failing.

---

### 2. Graph Layer — "How things connect"

Takes parsed data from all files → builds a connected graph → constructs flow DAGs from entry points.

```
┌─────────────────────────────────────────────────────────┐
│                     GRAPH LAYER                          │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Call Graph Builder                    │    │
│  │                                                   │    │
│  │  Input:  list[ParsedModule] (all files)          │    │
│  │                                                   │    │
│  │  Step 1: Build global function registry           │    │
│  │          {qualified_name → ParsedFunction}        │    │
│  │                                                   │    │
│  │  Step 2: For each function, resolve its calls     │    │
│  │          to entries in the registry               │    │
│  │                                                   │    │
│  │  Step 3: Create edges (caller → callee)          │    │
│  │          Mark edge type (CALLS, ASYNC, SIGNAL)    │    │
│  │                                                   │    │
│  │  Output: Global call graph (all functions, all    │    │
│  │          edges, unresolved calls marked)           │    │
│  └─────────────────────────────────────────────────┘    │
│                          │                               │
│                          ▼                               │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Flow DAG Builder                     │    │
│  │                                                   │    │
│  │  Input:  Global call graph + entry point          │    │
│  │                                                   │    │
│  │  Step 1: Start at entry point node               │    │
│  │  Step 2: BFS/DFS traversal following edges       │    │
│  │  Step 3: At conditionals → fork into branches    │    │
│  │  Step 4: At async boundaries → mark and continue │    │
│  │  Step 5: Detect cycles → mark and stop           │    │
│  │  Step 6: Track depth → stop at max_depth         │    │
│  │                                                   │    │
│  │  Output: FlowDAG (nodes, edges, branches,        │    │
│  │          files_touched, async_boundaries)          │    │
│  └─────────────────────────────────────────────────┘    │
│                          │                               │
│                          ▼                               │
│  ┌─────────────────────────────────────────────────┐    │
│  │              DAG Serializer                        │    │
│  │                                                   │    │
│  │  FlowDAG → JSON (for CLI / VS Code / Web)       │    │
│  │  FlowDAG → Mermaid (for markdown export)         │    │
│  │  FlowDAG → DOT (for Graphviz export)             │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**Abstraction contract:**
```python
class CallGraphBuilder:
    def build(self, modules: list[ParsedModule]) -> CallGraph

class FlowDAGBuilder:
    def build(self, graph: CallGraph, entry: EntryPoint, max_depth: int) -> FlowDAG

class Serializer(Protocol):
    def serialize(self, dag: FlowDAG) -> str  # JSON, Mermaid, DOT, etc.
```

**Scaling concern #1: Graph size.** A codebase with 2000 functions and 10,000 call edges is manageable. A monorepo with 50,000 functions creates a graph that's expensive to traverse for every entry point.

**Mitigation:**
- Lazy DAG building — only build the DAG for an entry point when requested, not upfront for all 509 entry points
- Depth limiting — default max_depth=10, configurable
- Scope pruning — user can specify "only trace within these modules" to exclude irrelevant subtrees

**Scaling concern #2: Cross-repo calls.** Microservice architectures where Service A calls Service B via HTTP/gRPC. The call graph stops at the HTTP client call.

**Mitigation (future):**
- Multi-repo mode where CARTOGRAPH parses multiple repos and links them via API contract matching (URL patterns in caller match route definitions in callee)
- For now, mark HTTP/gRPC calls as `EXTERNAL_CALL` with the URL as metadata

**Potential blocker:** Dynamic dispatch and metaprogramming. `getattr(module, func_name)()` can't be resolved statically. Python's `@generic_api_controller` decorator in turbomechanica-server generates methods at runtime.

**Mitigation:** This is exactly where the LLM layer helps. Static analysis finds 80% of calls. LLM infers the remaining 20% from patterns and documentation.

---

### 3. LLM Layer — "What it means to a human"

Takes the structural graph → adds semantic understanding → generates stories and annotations.

```
┌─────────────────────────────────────────────────────────┐
│                      LLM LAYER                           │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Story Generator                      │    │
│  │                                                   │    │
│  │  Input:  Call graph + entry points + docs         │    │
│  │                                                   │    │
│  │  Prompt: "Given these entry points and their      │    │
│  │  call trees, identify the top user stories.       │    │
│  │  For each: name, description, trigger, key        │    │
│  │  decision points."                                │    │
│  │                                                   │    │
│  │  Output: list[UserStory] with entry point refs    │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Flow Annotator                       │    │
│  │                                                   │    │
│  │  Input:  FlowDAG (structural) + docs             │    │
│  │                                                   │    │
│  │  Prompt: "For each node in this flow, provide     │    │
│  │  a 1-line human-readable description. For each    │    │
│  │  branch, explain the business meaning of the      │    │
│  │  condition."                                      │    │
│  │                                                   │    │
│  │  Output: Annotated FlowDAG                        │    │
│  │    - Node descriptions in plain English           │    │
│  │    - Branch labels ("anomaly detected" not        │    │
│  │      "if violation_count > 0")                    │    │
│  │    - Blast radius annotations                     │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Query Engine                         │    │
│  │                                                   │    │
│  │  Input:  Natural language question + call graph   │    │
│  │                                                   │    │
│  │  "What happens when Redis goes down?"             │    │
│  │  "Show me all writes to SensorData"               │    │
│  │  "What's the blast radius of changing auth?"      │    │
│  │                                                   │    │
│  │  Output: Relevant subgraph + explanation          │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Dynamic Resolver                     │    │
│  │                                                   │    │
│  │  Input:  Unresolved calls from static analysis    │    │
│  │                                                   │    │
│  │  "generic_api_controller generates CRUD methods   │    │
│  │   at runtime. What methods does it create for     │    │
│  │   EquipmentApiController?"                        │    │
│  │                                                   │    │
│  │  Output: Inferred function signatures + edges     │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**Abstraction contract:**
```python
class LLMProvider(Protocol):
    def generate(self, prompt: str, context: dict) -> str

class StoryGenerator:
    def __init__(self, provider: LLMProvider): ...
    def generate_stories(self, graph: CallGraph, docs: list[str]) -> list[UserStory]

class FlowAnnotator:
    def __init__(self, provider: LLMProvider): ...
    def annotate(self, dag: FlowDAG, docs: list[str]) -> FlowDAG

class QueryEngine:
    def __init__(self, provider: LLMProvider): ...
    def query(self, question: str, graph: CallGraph) -> QueryResult
```

**Scaling concern #1: Token limits.** A codebase with 2000 functions can't fit in a single LLM context window. Even with 200K context (Claude), the full AST dump of a large project exceeds limits.

**Mitigation: Multi-pass architecture (critical design decision):**
```
Pass 1: Parse (no LLM)        → Structural graph
Pass 2: Summarize per module   → LLM sees one module at a time, produces summary
Pass 3: Story generation       → LLM sees summaries + entry points, not full code
Pass 4: Flow annotation        → LLM sees one DAG at a time, not the full graph
```

Each LLM call is scoped to a bounded context (one module, one DAG, one query). The graph layer does the heavy lifting of connecting them. This means CARTOGRAPH works on codebases of ANY size — the LLM never needs to see the whole thing at once.

**Scaling concern #2: Cost.** Claude API calls per module × number of modules = expensive for large codebases.

**Mitigation:**
- LLM is optional. Structural graph + framework detection works without it.
- Cache LLM results in `.cartograph/`. Only re-run for changed files.
- Tiered usage: free (no LLM, structural only) → paid (LLM-annotated stories)

**Scaling concern #3: Provider lock-in.**

**Mitigation:** `LLMProvider` protocol. Swap Claude for GPT, Gemini, local Ollama, or no LLM at all. The graph layer doesn't know or care which provider is behind the annotation.

**Potential blocker:** LLM hallucination. The LLM might infer connections that don't exist or misinterpret framework patterns.

**Mitigation:** LLM ONLY annotates — it never creates nodes or edges. The structural graph from static analysis is the source of truth. LLM adds human-readable labels on top. Wrong label = cosmetic issue. Wrong edge = structural bug. By keeping these separate, hallucination can't corrupt the graph.

---

### 4. Cache Layer

```
┌─────────────────────────────────────────────────────────┐
│                     CACHE LAYER                          │
│                                                          │
│  .cartograph/                                            │
│  ├── index.json          # file_path → MD5 hash         │
│  ├── modules/            # Parsed AST per file           │
│  │   ├── alerts.tasks.json                              │
│  │   ├── equipments.pipeline.json                       │
│  │   └── ...                                             │
│  ├── graph.json          # Global call graph             │
│  ├── stories/            # LLM-generated stories         │
│  │   ├── story_001.json                                 │
│  │   └── ...                                             │
│  ├── flows/              # Built DAGs per entry point    │
│  │   ├── trigger_equipment_pipeline.json                │
│  │   └── ...                                             │
│  └── config.json         # Analysis configuration        │
│                                                          │
│  Invalidation strategy:                                  │
│  1. On init: hash every .py file                        │
│  2. Compare with stored hashes in index.json            │
│  3. Re-parse only changed files                         │
│  4. Re-build only affected DAGs (files_touched match)   │
│  5. Re-run LLM only for affected stories                │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**Scaling concern:** First run on a 500-file codebase = 5-10 seconds parse. Subsequent runs with 3 changed files = <1 second. Without caching, every `cartograph trace` would re-parse the entire project.

---

### 5. Render Layer (Phase 2+)

```
┌─────────────────────────────────────────────────────────┐
│                     RENDER LAYER                         │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │              DAG Renderer                         │    │
│  │                                                   │    │
│  │  Input:  FlowDAG (JSON)                          │    │
│  │  Output: Interactive visualization               │    │
│  │                                                   │    │
│  │  ┌──────────────┐                                │    │
│  │  │   D3.js +    │  ← VS Code Webview            │    │
│  │  │   dagre      │  ← Web UI                      │    │
│  │  └──────────────┘                                │    │
│  │  ┌──────────────┐                                │    │
│  │  │   Mermaid    │  ← Markdown export             │    │
│  │  └──────────────┘                                │    │
│  │  ┌──────────────┐                                │    │
│  │  │   Rich       │  ← CLI (current, tree format)  │    │
│  │  └──────────────┘                                │    │
│  │                                                   │    │
│  │  Interactions:                                    │    │
│  │  - Click node → open file at line                │    │
│  │  - Hover node → show description + annotations   │    │
│  │  - Click branch → highlight path to leaf         │    │
│  │  - Collapse/expand subtrees                      │    │
│  │  - Search within DAG                             │    │
│  │  - Filter by: async only, errors only, ORM only  │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

### 6. Provider Layer

```
┌─────────────────────────────────────────────────────────┐
│                    PROVIDER LAYER                         │
│                                                          │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐    │
│  │   Claude     │ │   OpenAI     │ │   Ollama     │    │
│  │   (API)      │ │   (API)      │ │   (Local)    │    │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘    │
│         │                │                 │             │
│         ▼                ▼                 ▼             │
│  ┌─────────────────────────────────────────────────┐    │
│  │              LLMProvider Protocol                 │    │
│  │                                                   │    │
│  │  generate(prompt, context) → str                 │    │
│  │  generate_structured(prompt, schema) → dict      │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
│  Config (.cartograph/config.json):                       │
│  {                                                       │
│    "llm_provider": "claude",                            │
│    "llm_model": "claude-sonnet-4-20250514",                    │
│    "api_key_env": "ANTHROPIC_API_KEY"                   │
│  }                                                       │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## Data Flow — End to End

```
Source Files (.py, .java, .go)
        │
        ▼
   ┌─────────┐
   │  PARSE  │  Language Parser + Framework Detectors + Module Resolver
   └────┬────┘
        │
        ▼
  list[ParsedModule]  ←── cached in .cartograph/modules/
        │
        ▼
   ┌─────────┐
   │  GRAPH  │  Call Graph Builder (global function registry + edge resolution)
   └────┬────┘
        │
        ▼
    CallGraph  ←── cached in .cartograph/graph.json
        │
        ├──────────────────────────────────┐
        ▼                                  ▼
   ┌─────────┐                      ┌──────────┐
   │  FLOW   │  DAG Builder         │   LLM    │  Story Generator
   │  BUILD  │  (per entry point)   │  STORIES │  (optional)
   └────┬────┘                      └────┬─────┘
        │                                │
        ▼                                ▼
    FlowDAG (structural)          list[UserStory]
        │                                │
        ├────────────────────────────────┘
        ▼
   ┌─────────┐
   │   LLM   │  Flow Annotator (optional)
   │ ANNOTATE│
   └────┬────┘
        │
        ▼
    FlowDAG (annotated)  ←── cached in .cartograph/flows/
        │
        ▼
   ┌─────────┐
   │ RENDER  │  CLI (Rich) / VS Code (D3.js) / Export (Mermaid, JSON)
   └─────────┘
```

---

## Abstraction Boundaries — Where We Can Scale Without Rewriting

```
                    STABLE                    PLUGGABLE
                (don't change)              (add new ones)
              ─────────────────           ─────────────────

Graph Models     ████████████████
(Node, Edge,     ████████████████
 FlowDAG)        ████████████████

Call Graph       ████████████████
Builder          ████████████████

DAG Builder      ████████████████

Serializer       ████████████████

                                    Language Parsers
                                    ░░░░░░░░░░░░░░░░  Python, Java, Go, JS...

                                    Framework Detectors
                                    ░░░░░░░░░░░░░░░░  Django, Celery, Spring...

                                    LLM Providers
                                    ░░░░░░░░░░░░░░░░  Claude, GPT, Ollama...

                                    Render Targets
                                    ░░░░░░░░░░░░░░░░  CLI, VS Code, Web, Mermaid...

                                    Cache Backends
                                    ░░░░░░░░░░░░░░░░  File, SQLite, Redis (future)...
```

**The rule:** Everything on the left is universal. Everything on the right is a plugin. Adding Java support means adding a plugin, not modifying the core. Adding a new LLM provider means implementing one protocol, not touching the graph engine. This is where most tools fail — they bake language-specific logic into the graph layer and can't scale.

---

## Potential Blockers & Mitigations

| # | Blocker | Severity | Mitigation |
|---|---------|----------|------------|
| 1 | **Dynamic dispatch** — `getattr()`, runtime-generated methods, metaclasses | High | LLM Dynamic Resolver as a fallback. Mark unresolvable calls as `EXTERNAL`. Don't fail, degrade gracefully. |
| 2 | **Module resolution in complex projects** — `sys.path` manipulation, namespace packages, conditional imports | High | Best-effort resolver. Allow user to configure additional import roots in `.cartograph/config.json`. |
| 3 | **Token limits for large codebases** — 50K+ functions won't fit in any context window | Medium | Multi-pass architecture. LLM never sees full codebase. Each call is scoped to one module or one DAG. |
| 4 | **Cross-repo / microservice calls** — HTTP/gRPC calls to other services | Medium | Phase 2: multi-repo mode. Phase 1: mark as EXTERNAL_CALL with URL metadata. |
| 5 | **LLM hallucination** — generates fake connections or wrong annotations | Medium | LLM never creates structural data (nodes/edges). Only annotates. Wrong label = cosmetic. Wrong edge = impossible. |
| 6 | **Performance on monorepos** — parsing 10K+ files | Low | Incremental parsing via file hash cache. Lazy DAG building (build on request, not upfront). |
| 7 | **Framework version changes** — Django 5 vs Django 4, Celery 6 vs Celery 5 | Low | Framework detectors are pattern-based (decorator names, method names), not version-specific. Rarely break across minor versions. |
| 8 | **Generated code** — protobuf stubs, ORM migrations, auto-generated APIs | Low | Exclude patterns in config (already excluding `migrations/`). User-configurable exclude list. |

---

## Phase Roadmap

```
Phase 1 (NOW):     Parse Layer (Python) + Graph Layer + CLI
                   ✓ AST parser working
                   ✓ Entry point detection (509 found)
                   ✓ Call tree tracing with async detection
                   → Module resolver
                   → Framework detectors (Django Ninja, Celery)
                   → Call graph builder (cross-file resolution)
                   → JSON serializer
                   → Cache layer

Phase 2:           LLM Layer + VS Code Extension
                   → Story generator
                   → Flow annotator
                   → VS Code webview with D3.js DAG
                   → Click-to-navigate

Phase 3:           Interactive Features
                   → Natural language query engine
                   → Diff mode (flow changes between branches)
                   → Filter/search within DAGs

Phase 4:           Multi-Language
                   → Tree-sitter integration
                   → Java + Spring Boot
                   → Go + net/http
                   → JavaScript + Express

Phase 5:           Scale
                   → Multi-repo / microservice linking
                   → LLM dynamic resolver
                   → Web UI (standalone, not VS Code)
                   → Team features (shared annotations, comments)
```
