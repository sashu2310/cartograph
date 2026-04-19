# Cartograph v2

**Harnessing deterministic context for LLMs.**

Cartograph reads your Python project with Tree-sitter, resolves cross-file calls through `ty` over LSP, and hands you the call graph — as a CLI tree, a browser DAG, markdown for pipe-to-LLM, structured JSON, or MCP tools an agent can call directly. The bits LLMs would hallucinate (which function does this import actually point at, is this a sync call or a Celery dispatch, where are the real entry points) are exactly the bits a type checker already knows. This tool is the bridge.

Linux + macOS. Python 3.11+. Open source, MIT.

---

## 5-minute quickstart

```bash
# Install — assumes uv is on PATH (https://github.com/astral-sh/uv)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
uv tool install ty       # the resolver; required
```

Scan a project once and remember it:

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
(saved as last project: /home/you/code/my-app)
```

Ask questions from anywhere — after `init`, path is optional:

```bash
$ carto2 entries --kind api_route
$ carto2 trace checkout --depth 3                # call tree, call-site lines
$ carto2 callers send_email                      # reverse lookup
$ carto2 search checkout                         # ranked by function name
$ carto2 analyze                                 # N+1, hotspots, async boundaries
$ carto2 dead                                    # unreachable functions/classes
$ carto2 impact --rename old.qname:new_name      # what breaks on rename
$ carto2 serve                                   # browser DAG at :3333
```

Pipe a flow into any LLM:

```bash
$ carto2 context checkout | claude "explain this flow and flag risks"
$ carto2 context --answer "what calls checkout" | claude
$ carto2 context checkout --max-tokens 2000 | claude
```

Or plug it into an agent natively (MCP):

```bash
$ claude mcp add cartograph -- carto2 mcp ~/code/my-app
```

That's the tour. Everything below is reference.

---

## How it works (60 seconds)

A 5-stage async pipeline: **extract** (Tree-sitter → syntactic IR) → **resolve** (`ty` LSP → typed edges) → **annotate** (six framework detectors → semantic labels) → **discover** (topology rule + labels → typed entry points) → **present** (CLI / web / markdown / MCP). Stage boundaries are frozen pydantic IRs; extraction and resolution are both content-hash cached. Full design in [`architecture.md`](./architecture.md), navigation in [`HLD.md`](./HLD.md).

---

## Command reference

Every command accepts `--help`. Path is optional after `carto2 init` (falls back to last-scanned project). Commands that take a qualified name (`trace`, `callers`, `explain`, `context`) accept exact (`my.pkg.mod.fn`), unique suffix (`fn`), or substring (`f`) — first hit wins. On no match, the top-5 substring candidates are suggested.

### `carto2 init PATH [--include-tests]`

Scan a project and persist the path for later commands. Without this, every other command requires `PATH`.

```bash
$ carto2 init ~/code/my-app --include-tests
```

### `carto2 scan [PATH] [--include-tests]`

Rerun the pipeline and print a rich-rendered summary (modules, functions, edges, entry points grouped by kind). Cache-hit on unchanged project returns in milliseconds.

### `carto2 entries [PATH] [--kind KIND]`

List discovered entry points, one per line. `--kind` filters by `api_route`, `celery_task`, `signal_handler`, or `discovered`.

```bash
$ carto2 entries --kind celery_task
celery_task   myapp.tasks.send_email
celery_task   myapp.tasks.reconcile
```

### `carto2 trace QNAME [PATH] [--depth N] [-o FILE]`

Walk the call tree rooted at QNAME. Prints a rich-coloured indented tree by default; with `-o`, writes a JSON document (nodes + edges + metadata — the same shape the web viewer consumes, suitable for `jq` pipelines).

- `--depth, -d N` — max recursion depth. Default 5. Range 1–10.
- `-o, --output FILE` — emit JSON to FILE instead of printing.

```bash
$ carto2 trace checkout --depth 3
$ carto2 trace checkout -o trace.json
```

### `carto2 callers QNAME [PATH]`

Reverse lookup — every function that calls QNAME, with line numbers.

```bash
$ carto2 callers process_payment
myapp.routes.checkout        (line 142)
myapp.tasks.retry_payment    (line 87)
```

### `carto2 search QUERY [PATH] [--limit N]`

Substring search over qualified names. `--limit` caps results (default 20, max 100).

### `carto2 serve [PATH] [--host HOST] [--port PORT]`

Run the interactive Cytoscape.js DAG viewer. Auto-loads the first entry point on open; click any node to walk its flow. Async edges are pink-dashed with their kind label (`delay`, `apply_async`, `chain`, `chord`, `group`); cross-file edges are purple; conditional edges carry their condition inline.

- `--host` default `127.0.0.1`
- `--port` default `3333`

### `carto2 explain QNAME [PATH] [--depth N] [--model MODEL]`

LLM-narrate the flow rooted at QNAME. Uses pydantic-ai; provider string via `--model` or `CARTOGRAPH_LLM_MODEL` env. Requires the matching API key (Anthropic, OpenAI) or a local Ollama instance.

```bash
$ carto2 explain checkout --model anthropic:claude-sonnet-4-5
```

> Note: `explain` re-introduces probability to a deterministic pipeline. When you want ground truth for an agent, prefer `context` or the MCP server.

### `carto2 context [QNAME] [PATH] [--depth N] [--answer Q] [--max-tokens N]`

Emit markdown facts for piping to an external LLM. Without QNAME: codebase-level markdown (stats + entry points + top callers + top classes). With QNAME: flow-level markdown (call tree with file:line refs).

`--answer Q` scopes the output to a specific question shape. Recognised patterns (case-insensitive):

- `"what calls X"` / `"callers of X"` / `"who calls X"` → inverse lookup
- `"what does X call"` / `"calls from X"` → one-hop callees
- `"flow of X"` / `"trace of X"` → full call tree (same as positional form)

`--max-tokens N` caps the flow-context output at roughly N tokens via greedy BFS (chars/4 heuristic). Stops cleanly at the budget, appends a truncation footer.

```bash
$ carto2 context | claude "explain this codebase"
$ carto2 context checkout | claude "explain this flow"
$ carto2 context --answer "what calls checkout" | claude
$ carto2 context --answer "what does process_payment call" | claude
$ carto2 context checkout --max-tokens 2000 | claude
```

### `carto2 analyze [PATH] [-o FILE]`

Engineering-insight analyses over the graph: N+1 ORM candidates, per-model hotspots, mixed-operation functions (read+write+delete in one body), async-boundary crossings (DB access + Celery dispatch in the same function). Rich tables by default; `-o file.json` emits the full `AnalysisReport` IR for scripting.

ORM analyses gate on `django.db.models` being imported somewhere in the project; if not, they return zero findings (never false positives on non-Django code).

### `carto2 dead [PATH] [-o FILE]`

Report functions and classes with zero incoming edges that aren't entry points — candidates for deletion pending review for dynamic dispatch. Grouped by kind (function / method / class); dunder methods and `main`/`__main__` are excluded.

Heuristic: dynamic dispatch (`getattr`, `__getattr__`, string-indexed callable dicts) bypasses the static graph, so the report is a starting list for review, not a deletion list.

### `carto2 impact --rename old.qname:new_name [PATH] [-o FILE]`

Enumerate every call site that would break if `old.qname` were renamed to `new_name`. Read-only — emits a patch plan, never modifies files. Exact line numbers from the graph, not grep-guessing. Imports of the old name are not yet enumerated (TODO — `ImportStmt` needs line numbers).

```bash
$ carto2 impact --rename auth.verify_token:verify_session
```

### `carto2 mcp [PATH]`

Run an MCP server on stdio, exposing seven tools (`scan`, `entries`, `trace`, `callers`, `search`, `context`, `analyze`) to agent hosts. See [MCP integration](#mcp-integration).

### `carto2 benchmark [PATH] [--targets LIST]`

Run both v1 and v2 pipelines on the same project and report pairwise structural overlap (Jaccard + shared/only-X edge counts). `--targets` defaults to `v1,v2-ty`.

### Top-level flags

- `-v, --verbose` — stream stage-timing spans (extract, resolve, annotate, discover) to stderr. Place before the subcommand: `carto2 -v trace …`.

---

## MCP integration

`carto2 mcp` speaks [Model Context Protocol](https://modelcontextprotocol.io) over stdio. Register with Claude Code:

```bash
claude mcp add cartograph -- carto2 mcp /path/to/your/project
```

Or configure directly in Claude Desktop, Cursor, Zed, Continue — every major agent host speaks MCP. The graph is built lazily on the first tool call and held in memory for the server's lifetime; restart the server to pick up file changes.

**Tools exposed:** `scan`, `entries`, `trace`, `callers`, `search`, `context`, `analyze`.

**Tools *not* exposed:** `explain`. The agent already has an LLM; our job is ground truth, not narration. `explain` stays on the CLI for humans who want prose.

---

## Configuration

### LLM (for `explain` / the narrator)

```bash
export CARTOGRAPH_LLM_MODEL="anthropic:claude-sonnet-4-5"   # default
export ANTHROPIC_API_KEY="..."

# or
export CARTOGRAPH_LLM_MODEL="openai:gpt-4o"
export OPENAI_API_KEY="..."

# or any Ollama model
export CARTOGRAPH_LLM_MODEL="ollama:llama3.1"
```

### Logging

```bash
export CARTOGRAPH_LOG=warn    # default; stage spans silenced
export CARTOGRAPH_LOG=info    # stream stage timings to stderr (same as `-v`)
```

### Caches & state

| Path | What |
|---|---|
| `<project>/.cartograph/v2/extract/` | Per-file parsed output, keyed by blake2b of file bytes |
| `<project>/.cartograph/v2/resolve/` | Whole-graph resolved output, keyed by blake2b of all file hashes + resolver version |
| `~/.cartograph/last_project_v2` | Last-used path (set by `init`, read when path arg is omitted) |

No manual cache management needed. First scan is slow (LSP cold-start + resolution); subsequent scans with no changes hit both caches and return in milliseconds. Touch a file → that file re-parses; change anything → Stage 2 reruns for the whole project (per-module incremental resolve is deferred to v2.1 — see [roadmap](./roadmap-v2.1.md)).

Bust everything: `rm -rf <project>/.cartograph/v2`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `command not found: ty` | `uv tool install ty`; confirm `ty --version` |
| Web viewer shows empty canvas | Hard-refresh to bust cached JS; check browser console for CDN errors |
| `no project path given and no previous init found` | Run `carto2 init <path>` once, or pass `<path>` to every command |
| Cache seems stale | `rm -rf <project>/.cartograph/v2` and re-scan |
| LLM narration errors | Check `CARTOGRAPH_LLM_MODEL` + the matching API key |
| LSP query timeouts on huge repos | Increase the client-side timeout in `cartograph/v2/stages/resolve/lsp/client.py` (default 2s per query) |
| MCP tools not appearing in Claude Code | `claude mcp list` to confirm registration; restart the host |

---

## Further reading

- [`architecture.md`](./architecture.md) — design record, key decisions, 4-repo benchmark, honest limitations (whitepaper)
- [`HLD.md`](./HLD.md) — module map + data flow + where-to-look table (navigation)
- [`v1-vs-v2.md`](./v1-vs-v2.md) — exhaustive diff for v1 maintainers
- [`roadmap-v2.1.md`](./roadmap-v2.1.md) — what ships after v2.0, ranked by leverage
