# Cartograph v2.2 — roadmap

**Harnessing deterministic context for LLMs.** v2.2 is about *correctness* and *ergonomics* on top of v2.0's scaffolding: kill the false-positive classes our dogfood surfaced, add the query shapes the v2.1 roadmap promised, and graduate framework detection from hardcoded-per-framework to generic-via-type-inference.

---

## Scope — 13 items, one table

| # | Item | Source | Phase | Status | Commit |
|---|---|---|---|---|---|
| 1 | Type-verified ORM annotator (import gate + Model-class identification + verified receivers) | dogfood P0 | 1. correctness | ✅ | `c72f2bf` |
| 2 | Unresolved breakdown by reason — surfaced in CLI / markdown / JSON API / MCP tools | dogfood P1 | 1. correctness | ✅ | `a907490` |
| 3 | Trace shows **call-site line** from the caller, not callee definition line | dogfood P1 | 1. correctness | ✅ | `93bfe04` |
| 4 | Consistent entry-point rendering — shared `_pretty_entry_line` across scan/entries/context | dogfood P2 | 1. correctness | ✅ | `a907490` |
| 5 | Classes surfaced in scan summary, codebase markdown, `/api/overview`, MCP `scan` | dogfood P2 | 1. correctness | ✅ | `a907490` |
| 6 | Ranked search — function name scored above module-path match | dogfood P2 | 1. correctness | ✅ | `5266141` |
| 7 | Cache visibility — `(resolve cache hit — 2.4s)` footer | dogfood P3 | 1. correctness | ✅ | `fcde908` |
| 8 | `carto2 context --answer "what calls X"` — question-scoped subgraph | v2.1 roadmap | 2. new queries | ✅ | `8ffa4b1` |
| 9 | `carto2 context --max-tokens N` — token-budget-aware greedy BFS | v2.1 roadmap | 2. new queries | ✅ | `8ffa4b1` |
| 10 | `carto2 impact --rename old:new` — rename-impact analysis (read-only patch plan) | v2.1 roadmap | 2. new queries | ✅ | `2739e9b` |
| 11 | `carto2 dead` — dead-code report (unreachable from any entry point) | v2.1 roadmap | 2. new queries | ✅ | `2c2deae` |
| 12 | mtime Stage 1 fast path — `path → (mtime, hash)` secondary index | v2.1 roadmap | 3. perf | ✅ | `d8eeda5` |
| 13 | **Decorator call semantics via type inference** — generic metadata extraction, annotators become thin translators | dogfood follow-up | 4. architectural | ✅ | `fcb96d4` |

**Legend:** ✅ shipped · ⏳ pending · source = dogfood P0/P1/P2/P3 (newbie walkthrough on pydantic-ai) or v2.1 roadmap (the doc we wrote before the dogfood test).

---

## Phase ordering (sequential — no parallel tracks)

1. **Correctness** (items 1–7). Close every finding from the pydantic-ai dogfood. Demo-ready after this.
2. **New queries** (items 8–11). Agent-UX multipliers from the v2.1 roadmap.
3. **Perf** (item 12). Internal, no UX churn.
4. **Architectural** (item 13). The big one. Lands last with confidence the base is stable.

Every item lands as its own commit on the `v2` branch. Sashu can cherry-pick individually.

---

## Why item #13 is the big one

Current Stage 3 (Annotate) has an asymmetry:

- **Topology discovery** (Stage 4) is **generic**: "decorator + zero in-edges + ≥1 out-edge" works on any framework, any custom decorator, any plugin hook. That's the core novelty.
- **Semantic metadata** (Stage 3) is **hardcoded per framework**: six `Annotator` implementations, each pattern-matching specific decorator names (`@app.get`, `@receiver`, `@celery_app.task`) to extract specific fields (method, path, signal_name, queue, bind). Adding a framework = writing new Python code.

The effect: topology finds a custom decorator like `@instrumented_task("billing", priority=True)`, but its metadata surfaces as the bare decorator name. The agent gets "this is an entry point" but not "it registers a billing task with priority." The framework-specific richness is behind a gate only we (the tool authors) can open.

### The v2.2 delta

We already run `ty` over every call site. A decorator *is* a call: `@app.get("/x")` is a call to `app.get` with arg `"/x"`. What we do with call sites — resolve the target via `textDocument/definition`, look at its type signature, classify it — generalises to decorators.

**New design, one layer:**

1. **Stage 2** resolves decorator targets alongside call sites. Each `DecoratorSpec.name` becomes a resolved `FunctionRef` (plus the `SyntacticFunction`'s own typed signature from `ty`).
2. **Bind positional args to parameter names** using the decorator's type signature. `@app.get("/x")` with signature `def get(path: str, *, response_model=None, ...)` → `bindings = {"path": "/x"}`. Framework-agnostic.
3. **A new `DecoratorCallLabel(target: FunctionRef, bindings: dict[str, str])`** variant on `SemanticLabel`. Machine-readable regardless of framework.
4. **Framework annotators collapse to translators.** The FastAPI annotator becomes: "if `target.qname.startswith('fastapi.')` and bindings contains `path` → emit `ApiRouteLabel`." ~10 lines per framework instead of ~50.
5. **Custom decorators gain metadata automatically.** `@instrumented_task("billing", priority=True)` — if `instrumented_task` has a typed signature, its args are surfaced in `bindings`. Even without a specific annotator, an agent reading the `DecoratorCallLabel` can reason about it.

### Why this is novel

- Static call-graph tools (`pyan`, `pydeps`, `code2flow`, pyright's graph dump) hardcode framework support or skip it entirely.
- Type-aware tools (pyright, mypy) don't propagate type information into decorator call metadata at an IR boundary.
- The combination — piping a real type checker's inference through decorator call semantics, into structured consumer-ready labels — isn't in the existing literature.

The pitch for a Google talk becomes: *"topology for discovery, type inference for semantics — both generic, neither framework-specific."*

### What will change in code

- `cartograph/v2/ir/annotated.py` — add `DecoratorCallLabel` variant to `SemanticLabel`.
- `cartograph/v2/stages/resolve/ty_resolver.py` — resolve decorator targets (one extra LSP query per decorator).
- `cartograph/v2/stages/annotate/frameworks/*.py` — all six annotators rewritten as thin translators over `DecoratorCallLabel`.
- `cartograph/v2/stages/present/*.py` — presenters surface the generic `bindings` for unknown decorators.

### What won't change

- Topology rule is untouched (it remains the core novelty).
- Stage 1 (Extract) unchanged.
- Stage 4 (Discover) — same promotion logic, just consuming richer labels.
- Public CLI/MCP surface — same commands, same tool names. New metadata flows through the existing channels.

---

## Anti-goals (unchanged from v2.1)

- **No LLM post-processors.** The graph is the product.
- **No heuristic fallbacks when `ty` can't resolve.** Unresolved stays unresolved, honestly reported.
- **No non-deterministic rankings.** Stable sort whenever output is sorted.
- **No embedding-based context filters.** Everything rule-based.

---

## Status snapshot

**13 of 13 items complete.** v2.2 ready to push. 11 commits landed on the `v2` branch between `ba4e40d` (this doc) and `fcb96d4` (decorator call semantics). See `git log main..v2 --oneline` for the full series.
