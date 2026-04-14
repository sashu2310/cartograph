# CARTOGRAPH — Path Forward

## Where We Are (10 commits, 2 days)

```
Phase 1: COMPLETE
├── Three-layer parser (LanguageAdapter + FrameworkDetector + Registry)
├── Call graph builder with cross-file import resolution
├── Type inference (constructor tracking, self.method(), annotated types)
├── 4 framework detectors (Celery, Django Ninja, Django ORM, Django Signals)
├── CLI: init, trace, summary, serve
├── Interactive web viewer (D3 + dagre, dark theme, three-panel)
├── 96 tests passing
└── Tested: Celery (1846 edges), paperless-ngx (49-node DAGs across 12 files)
```

## What's Next — Prioritized by Impact

### Priority 1: LLM Flow Narration (Phase 2 — highest differentiator)

**Why first:** "Don't read the code. Read the story" is the tagline. Without narration, CARTOGRAPH is a graph visualizer. With it, it's an AI-powered code explainer that no LLM can replicate alone (because the graph is exhaustive, the narration is grounded).

**What it does:**
- Click a node or entry point → "Explain this flow"
- LLM receives the subgraph JSON (nodes, edges, files, async boundaries)
- Returns a 2-3 paragraph narrative: what the flow does, what data it transforms, where it dispatches async work, what the branch conditions mean
- Displayed in the detail panel or as an overlay

**Implementation:**
1. `cartograph/llm/` — provider protocol (same pattern as VENN's adapter.py)
   - `LLMProvider` protocol: `narrate_flow(graph_json) -> str`
   - `ClaudeProvider`, `OpenAIProvider`, `OllamaProvider`
   - `get_llm_provider()` factory from env var
2. `cartograph/llm/prompts.py` — system prompt that teaches the LLM to read graph JSON
3. New API endpoint: `GET /api/narrate/{qname}` → returns `{"narrative": "..."}`
4. Web viewer: "Explain" button on entry points and detail panel
5. CLI: `cartograph explain <path> "function_name"` → prints narrative

**Prompt strategy:** Feed the LLM the subgraph JSON + file snippets for the root node. The graph gives structure, the code gives semantics. The LLM narrates from both.

### Priority 2: More Framework Detectors (Phase 2 — broader reach)

**Why:** paperless-ngx uses DRF ViewSets, not Django Ninja. FastAPI is the fastest-growing Python web framework. Without these detectors, the sidebar is empty for most projects.

1. **FastAPI detector** — `@app.get`, `@router.post`, `@app.websocket`
2. **DRF detector** — `class FooViewSet(ViewSet)` with `@action` decorators
3. **Flask detector** — `@app.route`, `@blueprint.route`

Each is ~50-80 lines following the existing `FrameworkDetector` protocol. Register in `core.py`.

### Priority 3: Polish for Public Launch

1. **PyPI publish** — `pip install cartograph` so anyone can try it
2. **README GIF** — 20-second recording of the web viewer against paperless-ngx
3. **Startup performance** — show Rich progress bar during parse, not just "parsing..."
4. **Error handling** — graceful fallback when LLM provider not configured
5. **`--exclude` flag** — CLI option to exclude directories beyond defaults

### Priority 4: Resolution Improvements

1. **Class hierarchy tracking** — parse `class Foo(Base):` and resolve `self.method()` to parent class methods. Would fix the remaining ~60% unresolved `self.x()` calls.
2. **Nested function parsing** — functions defined inside functions (Celery's `builtins.py` pattern). Would detect tasks in closure-based registration.
3. **Return type inference** — `x = get_backend()` where `get_backend` returns `RedisBackend` → track `x` as `RedisBackend`.

### Priority 5: Multi-Language Foundation (Phase 3)

1. **Tree-sitter integration** — replace stdlib `ast` with tree-sitter-python first (same output, incremental parsing, error tolerance)
2. **Java adapter** — tree-sitter-java + Spring Boot detector (`@RestController`, `@GetMapping`, `@Async`, `@Scheduled`)
3. **Go adapter** — tree-sitter-go + goroutine boundary detection (`go func()`, channel sends)
4. **TypeScript adapter** — tree-sitter-typescript + Express/Nest/Next detection

### Priority 6: Developer Experience (Phase 3)

1. **VS Code extension** — webview panel with same D3 rendering, click-to-navigate to source
2. **Diff mode** — `cartograph diff main..feature` → "what flows changed in this PR?"
3. **CI integration** — GitHub Action that generates flow docs on merge
4. **Watch mode** — `cartograph serve --watch` re-parses on file save

## Execution Order

```
Week 1: LLM narration (provider + prompt + API endpoint + web UI button)
Week 2: FastAPI + DRF + Flask detectors + PyPI publish
Week 3: README GIF + class hierarchy tracking + polish
Week 4: Public launch (HN, Reddit, Twitter)
---
Month 2: Tree-sitter migration + Java adapter
Month 3: VS Code extension + diff mode
```

## Key Architectural Principle

The engine is language-agnostic. The graph layer never changes. Every new capability is either:
- A new **LanguageAdapter** (parsing)
- A new **FrameworkDetector** (entry points + patterns)
- A new **LLMProvider** (narration)
- A new **Renderer** (web, VS Code, CI)

M + N, not M × N. This is the moat.
