# Cartograph

[![CI](https://github.com/sashu2310/cartograph/actions/workflows/ci.yml/badge.svg)](https://github.com/sashu2310/cartograph/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/cartograph-code)](https://pypi.org/project/cartograph-code/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Harnessing deterministic context for LLMs.**

Cartograph reads your Python project with Tree-sitter, resolves cross-file calls through `ty` over LSP, and hands you the call graph — as a CLI tree, a browser DAG, markdown to pipe into an LLM, structured JSON, or MCP tools an agent can call directly. The bits LLMs hallucinate — which function does this import resolve to, is this call sync or a Celery dispatch, where are the real entry points — are the bits a type checker already knows.

Linux + macOS. Python 3.11+. Open source, MIT.

---

## Install

Source install via `uv`:

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
uv tool install ty        # the resolver; required
```

> v1 (`pip install cartograph-code`, `carto` CLI) is still published and works, but new development lands on v2 (`carto2` CLI). See [`docs/v2/v1-vs-v2.md`](./docs/v2/v1-vs-v2.md) if you're migrating.

---

## Quickstart

```bash
$ carto2 init ~/code/my-app
CARTOGRAPH v2 — my-app
╭───── summary ─────╮
│  42  modules      │
│ 312  functions    │
│ 401  edges        │
│ 17   entry points │
╰───────────────────╯
api_route (8)
  GET    /users/{id}          → myapp.routes.get_user
  POST   /checkout            → myapp.routes.checkout
  ...
celery_task (4)
  myapp.tasks.send_email [priority]
  ...
```

After `init`, path is optional — every command falls back to the last-scanned project:

```bash
$ carto2 entries --kind api_route             # list routes with method + path
$ carto2 trace checkout --depth 3             # call tree with call-site lines
$ carto2 callers send_email                   # reverse lookup
$ carto2 search checkout                      # ranked by qualified name
$ carto2 analyze                              # N+1, hotspots, cycles, sync-in-async
$ carto2 dead                                 # unreachable functions/classes
$ carto2 impact --rename old.qname:new_name   # every call site that breaks
$ carto2 serve                                # Cytoscape DAG at :3333
```

Pipe a flow into any LLM:

```bash
$ carto2 context checkout | claude "explain this flow and flag risks"
$ carto2 context --answer "what calls checkout" | claude
```

Or register it as an MCP server so your agent can call the tools directly:

```bash
$ claude mcp add cartograph -- carto2 mcp ~/code/my-app
```

**Full command reference, caching details, MCP tools, troubleshooting** → [`docs/v2/README.md`](./docs/v2/README.md).

---

## Why bother

Most code-analysis tools hardcode decorator names (`@app.get` = route, `@shared_task` = celery). That breaks the moment a codebase wraps the framework — and real codebases always do.

Cartograph uses graph topology instead: a function is an entry point if it has a decorator, zero incoming edges, and at least one outgoing edge. Framework detectors (FastAPI, Flask, Django Ninja, Django Signals, Django ORM, Celery) still exist — they add semantic labels like `GET /api/users` — but discovery does not depend on them.

| Codebase | Framework-detector only | + Topology | Notes |
|----------|-------------------------|-----------|-------|
| Sentry | 52 | 788 | `@instrumented_task`, `@cell_silo_endpoint` |
| Dagster | 0 | 255 | `@public`, `@job_cli.command` — zero detectors exist |
| Polar | 328 | 600 | FastAPI routes + `@actor`, `@cli.command` |
| Prefect | 183 | 396 | FastAPI routes + `@flow`, `@task` |

Type resolution runs through `ty` (Astral's Python type checker) over LSP, so `receiver.method()` resolves the way the type checker resolves it — including factory classmethods, parameter annotations, and return types. What `ty` can't resolve is reported honestly as `Unresolved*`; there are no heuristic fallbacks that silently guess.

---

## Walkthrough

> GIFs recorded against v1; v2 renders the same shape.

**1. Scan** — parse the codebase, discover entry points, group by kind.
![carto scan](docs/demo_gifs/demo-scan-final.gif)

**2. Entries** — list every entry point, filter by kind.
![carto entries](docs/demo_gifs/demo-entries-final.gif)

**3. Trace** — walk the call graph from any function, with branch conditions on edges.
![carto trace](docs/demo_gifs/demo-trace-final.gif)

**4. Context** — collapse the whole codebase into structured markdown for an LLM.
![carto context](docs/demo_gifs/demo-context-final.gif)

**5. Pipe to Claude** — ask any LLM about any flow with full graph context.
![carto context | claude](docs/demo_gifs/demo-claude-final.gif)

---

## Design decisions

**Why Tree-sitter + `ty`, not stdlib `ast`?** `ast` gave us syntax but not types — Python call resolution needs a type checker. `ty` is fast, incremental, LSP-accessible, and under active development at Astral.

**Why topology for entry points?** A hardcoded decorator list is always incomplete. The graph already knows which functions are roots — use the structure, not the annotations.

**Why frozen typed IRs at each stage?** Every stage (`extract`, `resolve`, `annotate`, `discover`, `present`) emits pydantic models with `extra="forbid"` and `strict=True`. Makes the pipeline cacheable, diffable, and mutation-bug-free.

**Why pipe to an LLM instead of embedding one?** You already have one. Cartograph generates context; it's not an LLM wrapper. `carto2 context | claude` is the primary flow; `carto2 mcp` skips the pipe for agents; `carto2 explain` is the built-in for humans who want prose.

**Resolution ceiling:** ~65% of project-internal calls resolve on complex codebases. The rest are calls into external packages (Django ORM, stdlib, sentry_sdk) that no project-level analyzer can resolve — we report them as unresolved. Entry-point discovery is pure topology and doesn't depend on resolution.

---

## Further reading

- [`docs/v2/README.md`](./docs/v2/README.md) — command reference, caching, MCP, troubleshooting
- [`docs/v2/architecture.md`](./docs/v2/architecture.md) — design record, benchmark, honest limitations
- [`docs/v2/HLD.md`](./docs/v2/HLD.md) — module map + data flow
- [`docs/v2/v1-vs-v2.md`](./docs/v2/v1-vs-v2.md) — exhaustive diff for v1 maintainers
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — dev setup + how to add an analysis / framework / presenter

---

## License

MIT

*LLMs guess. Cartograph proves.*
