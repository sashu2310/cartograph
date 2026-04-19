# Cartograph v2.3 — roadmap

**Harnessing deterministic context for LLMs.** v2.0 was scaffolding, v2.2 was correctness and agent-UX. v2.3 closes the debt v2.2 carried, pays down shortcuts I took under time pressure, and extends the analyses layer beyond Django-specific checks — because a "no findings" report on a fastapi codebase is honest but not useful.

Skipping v2.4 as a release label, so v2.3 packs more. Organized by **cleanup → refactor → new work → ambitious** so the phase 1 items (the debt) ship before phase 3 items (new queries).

---

## Scope — 21 items, one table

| # | Item | Category | Source | Why |
|---|---|---|---|---|
| 1 | Import line numbers in `ImportStmt` | cleanup | v2.2 shortcut | Stage 1 currently drops the line; without it Tier 2 can't land fully |
| 2 | Full `impact --rename` import enumeration | cleanup | v2.2 shortcut | Today `impact` says "grep for imports yourself." With #1 we finish the feature. |
| 3 | MCP tools for `dead` + `impact` | cleanup | v2.2 gap | `dead` and `impact` ship on the CLI but aren't in MCP's 7 tools. Agents can't invoke them. Parity fix. |
| 4 | Annotator tests exercise the decorator-resolved path | cleanup | v2.2 gap | Current test fixtures only hit the syntactic fallback; the new type-resolved code path has no dedicated test. |
| 5 | Ty diagnostic cleanup | cleanup | ongoing | `Err_.value` narrowing, unused-param warnings, `stats.get()` type widening. Real bugs vs cosmetic — triage and fix. |
| 6 | Import-cycle detection | action: new analysis | user ask | `analyze` today is Django-only; cycles are framework-agnostic and actionable. Stage 1 imports → directed graph → Tarjan. |
| 7 | Sync-in-async detection | action: new analysis | user ask | `async def` calling `sync_blocking()` without `asyncio.to_thread`. Common bug on FastAPI / pydantic-ai stacks. Stage 1 already tracks sync vs async. |
| 8 | FastAPI path collisions | action: new analysis | user ask | Two routes with the same `method+path` on different handlers. We have the labels; join on `(method, path)`. |
| 9 | Dead class methods | action: new analysis | user ask | Method on a *used* class (construction-reached) but the method itself has no callers. Extends current `dead` logic with a method-only kind. |
| 10 | Long call chains | action: new analysis | user ask | Entry point → N-hop flow exceeding a threshold — refactor smell. Trivial: already walking the graph. |
| 11 | `--exclude-dirs DIR,DIR,...` CLI flag | action: UX | dogfood (fastapi `docs_src/` noise) | Per-invocation exclusions beyond the hardcoded `tests/` default. 5-line Click addition. |
| 12 | `--limit N` on `dead` / `analyze` | action: UX | dogfood (table-piped-to-head looks choppy) | In-command truncation so tables render complete borders even at 30-row cap. |
| 13 | Root `README.md` rewrite — v2-first | cleanup | dogfood | GitHub landing page still pitches `pip install cartograph-code` (v1) first, banner for v2 second. Invert it now that v2 is the canonical line. |
| 14 | `CONTRIBUTING.md` extension guide | cleanup | project health | Explicit "here's how to add an analysis / framework annotator / presenter" walkthrough. Currently implicit from reading the Protocol types. |
| 15 | Split `cli.py` into `cli/commands/` | refactor | maintainability | `cli.py` is ~800 lines, 14 commands. Split one command per module + a thin `__init__.py` that wires them. |
| 16 | Split `analyses/__init__.py` into per-analysis modules | refactor | maintainability | One file per check (`analyses/orm.py`, `analyses/dead.py`, `analyses/impact.py`). Imports stay stable via `__init__.py` re-exports. |
| 17 | Extract shared presenter utils | refactor | code reuse | `top_classes_by_usage`, `bucket_unresolved`, `ranked_search` live in `stages/present/cli.py` — not really "CLI presenter" concerns. Move to `stages/present/util.py` or `analyses/`. |
| 18 | Integration tests for v2.2 items | cleanup | test coverage | End-to-end tests for: mtime fast path behaviour, decorator resolution on a fastapi-ish fixture, cache hit/miss transitions, rename-impact's exact-line output. |
| 19 | Test-edge annotations | action: ambitious | v2.1 roadmap deferred | Shadow-scan `tests/` dir, compute reachability from test entries into main graph, flag each edge with `has_test_coverage: bool`. Gold for refactor confidence. |
| 20 | `carto2 diff <sha1> <sha2>` | action: ambitious | v2.1 roadmap deferred | Graph-diff between commits. Cache graphs keyed by commit SHA; set-diff edges/entries/labels. Code-review killer feature. |
| 21 | Type-surface exposure at call sites | action: ambitious | v2.1 roadmap deferred | Use `ty`'s hover to attach resolved arg/return types to `Edge` metadata. Lets agents answer "what fields does this expect" without reading the class def. |
| 22 | Web UI: generic, data-driven legend | action: UX | dogfood (celery swatch shown on non-celery project) | Legend was static HTML with framework-named swatches. Render only kinds actually present in the graph. |

**Legend:** *cleanup* = pays down v2.2 debt; *refactor* = structural change, no new behaviour; *action* = new user-visible feature; *ambitious* = tier-4 stretches kept in scope because we're skipping v2.4.

---

## Phase ordering

1. **Correctness / gap-closing** (items 1–5). Pay down v2.2 shortcuts before adding anything new. Stable foundation.
2. **New analyses** (items 6–10). Ships non-Django value to the `analyze` command — directly responsive to the "is this useful for me?" dogfood question.
3. **Ergonomics + docs** (items 11–14). Small, visible wins. Close the quick UX complaints.
4. **Refactors** (items 15–18). Internal cleanups + test coverage. Zero user-visible change, but the codebase stops feeling cramped.
5. **Ambitious** (items 19–21). The v2.1-roadmap stretches we deferred twice. Landing one of these is a bonus; all three is the "v2.4 absorbed into v2.3" promise.

Each item a separate commit on the `v2` branch. Same workflow as v2.2 — sashu reviews commit-by-commit on the PR.

---

## Why skip v2.4 as a release label

v2.0 was the MVP. v2.2 was correctness-plus-features. If v2.3 ships items 1–18 reliably plus at least one of 19–21, the tool is *feature-complete for the product line we've staked*: contextual determinism, agent-native distribution, framework-agnostic analyses, rename impact, dead code, graph diff. A v2.4 would be incrementally polishing that surface or adding a tenth analysis; real deltas from that point are v3 territory (decorator-target SDK, non-Python extractors, language-server mode).

Better to ship a substantial v2.3 and pause for real usage than ship v2.3-small + v2.4-small in sequence.

---

## Anti-goals (unchanged from v2.2)

- **No LLM post-processors.** The graph is the product.
- **No heuristic fallbacks when `ty` can't resolve.** Honest `Unresolved*` reporting.
- **No plugin system for analyses.** Still premature — hardcode new ones until external contributors demand otherwise.
- **No non-Python extractors.** `TreesitterExtractor` is positioned for TS/Go/Rust but each needs its own Resolver. v3.x concern.
- **No ML / embeddings / vector search.** Same reason as v2.2 — breaks determinism.

---

## Status snapshot

**13 of 22 items complete** (items 1–12 + the new #22 UI fix).
Commits land one-per-item on the `v2` branch. See `git log origin/v2..v2` for the unpushed stack.
