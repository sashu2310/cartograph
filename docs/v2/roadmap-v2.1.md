# Cartograph v2.1 — roadmap

**Harnessing deterministic context for LLMs.** That's the product line, and it's the only lens used to pick the items below. Every feature here is deterministic: same input, same output. No LLM post-processors, no heuristic fallbacks when `ty` can't resolve, no non-deterministic rankings. v2.1 is not about making v2 smarter — it's about making the determinism we already have *more consumable*, *more fine-grained*, and *faster on large repos*.

Sorted by leverage, not difficulty. The recommended v2.1 cut is at the bottom; the tiers above are the universe we picked from.

---

## Tier 1 — agent-UX multipliers

**Question-scoped context.** Today `carto2 context` dumps either a full codebase or a full flow. On a 1,000-function repo that's 30K+ tokens; most of them aren't relevant to whatever question the agent is trying to answer. v2.1 adds `--answer` (or `context(question=…)` over MCP) taking a small set of recognised tags — `what-calls`, `depends-on`, `path-from`, `flow-of` — and returning a subgraph sized to the question. The scoping rule is a pure function of the graph and the tag, so the output is reproducible across calls. This is the single biggest token-efficiency win available, and it plugs into every existing MCP client without re-training anyone.

**Token-budget-aware depth.** `--depth 5` is a usability proxy; agents have no way to predict how many tokens that produces. `--budget 4000` takes a token cap and does greedy BFS from the root until it exhausts the budget. Pair it with question-scoping and agents can say "give me as much context as fits in 4K tokens, about X." We'll document which tokenizer the budget is measured in (`tiktoken` with the model's encoding) so the budget is reproducible.

**Rename-impact mode.** `carto2 impact --rename old.qname:new_name` walks the graph for incoming edges and returns the exact call sites, with line numbers, that would break under the rename. This is where static analysis uniquely beats an LLM: grep-and-reason gets renames wrong on anything with overloaded names; graph lookup doesn't. The command is read-only — it emits a patch plan, doesn't apply it. Future work could hand that plan to a refactor tool.

## Tier 2 — refactor confidence

**Test-edge annotations.** Run the pipeline over `tests/` as a shadow graph, compute reachability from test entry points into the main graph, intersect sets. Each main-graph edge gets `has_test_coverage: bool` plus the list of test qnames that reach it. This is static reachability, not runtime coverage — but even static reachability is something agents currently can't answer from source alone, and it's the right signal for "can I refactor this edge?" Caveat: dynamic dispatch makes it conservative (may under-report coverage), not unsafe.

**Dead-code report.** `carto2 dead` lists functions with zero incoming edges, no decorator, and no reachable path from any entry point. Implementation is a set-subtraction over the reachable-from-entries set — maybe a day of work, immediately actionable. The false-positive risk is dynamic dispatch: a function called via `getattr` or registered in a string-indexed dict won't be reached by the graph walk. The report should flag low-confidence rows, not just emit a flat list.

## Tier 3 — scale and performance (internal)

**mtime-based Stage 1 fast path.** Today's ExtractCache hashes every file on every scan to decide cache hits — fast per file (blake2b is ~500 MB/s) but adds up to 200–500 ms on 30K-file monorepos. A secondary `path → (mtime, hash)` index lets unchanged files skip hashing entirely. mtime is a lossy proxy, but we only use it to skip hashing *bytes we've already hashed* — if mtime changed, we re-hash as today, so there's no correctness risk. This is the insight borrowed from v1's recent mtime-freshness commit; the architecture is ours, the idea is theirs.

**Incremental Stage 2 resolve.** Today, any file change busts the whole-project ResolveCache. Tracking per-module dependencies and re-resolving only the affected subgraph would fix this, but the implementation is genuinely complex — a module-level dependency DAG with inverse indexes, plus careful cache invalidation when a transitively-imported module changes. We keep the whole-graph cache because at 1–10K files it busts in milliseconds and the extra code doesn't pay for itself. At 50K+ files it becomes the long pole. Build this when someone actually has that codebase.

## Tier 4 — ambitious but legitimate

**Graph-diff between commits.** `carto2 diff <sha1> <sha2>` caches graphs by commit SHA and set-diffs edges, entries, and labels. Output: "this PR adds these edges, removes these, changes these entry points." It's the code-review killer feature: nobody currently runs static analysis twice on a diff and compares. Cost: git integration plus per-commit graph caching. Not small, not trivial, but the leverage is real.

**Type-surface exposure at call sites.** Today we resolve *identity* (what function is called); we don't surface *types* (what shapes the args and return take). Adding `textDocument/hover` (or whatever ty's equivalent is) at each call site would let agents answer "what fields does this request expect?" without reading the class def. Cost: another LSP query class, more round-trips per call site. Value: enormous for any agent trying to understand API shapes.

**Non-Python extractors (TypeScript, Go, Rust).** The `Extractor` protocol was designed for this — tree-sitter supports all three, and each language has a language server (`tsserver`, `gopls`, `rust-analyzer`) we could use as the Resolver. A language per week, roughly. The architecture is ready; nothing has been wired.

---

## Anti-goals

These will not ship in v2.1, because shipping them would betray the product line:

- **LLM post-processors.** No "smart" narration, no AI-reranked results. The graph is the product.
- **Heuristic fallbacks when `ty` can't resolve.** Unresolved stays unresolved; we report the reason honestly (`BuiltinUnresolved`, `ExternalUnresolved`, `LspUnresolved`, `UnknownUnresolved`). Guessing is how you lose agent trust.
- **Non-deterministic rankings.** If the output is sorted, the sort is stable across runs.
- **Embedding-based context filters.** "Most relevant edges" via vector similarity is the opposite of what this tool exists for.

---

## Recommended v2.1 cut

**Ship three features, ~one week of work:**

1. Question-scoped context — the biggest agent-UX unlock, pairs with existing MCP server.
2. Rename-impact mode — the strongest "static analysis beats LLM" pitch in the toolkit.
3. Dead-code report — fast to build, immediately useful, signals the analyses layer is a library not a demo.

**Include if time:** token-budget-aware depth (pairs naturally with #1) and the mtime Stage 1 fast path (internal, no UX churn).

**Defer to v2.2 and beyond:** everything else. Let v2.0 usage + the first three v2.1 items tell us which of test-edge / graph-diff / type-surface / non-Python actually matters. Designed-in-advance features usually over-engineer, under-ship, or solve the wrong problem.

**Do not build:** anything outside this list. The restraint that got v2 shippable — saying no to Typer, Textual, SQLite caches, fzf, orjson, rapidfuzz, a PyreflyResolver port — is not an aesthetic choice. It's the discipline.
