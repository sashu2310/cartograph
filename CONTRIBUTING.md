# Contributing to Cartograph

## Setup

Cartograph uses [uv](https://github.com/astral-sh/uv) for dependency management. Install it first:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

1. **Fork** the repo on GitHub: https://github.com/sashu2310/cartograph → click **Fork**.
2. **Clone and install:**

```bash
git clone https://github.com/<your-username>/cartograph.git
cd cartograph
git remote add upstream https://github.com/sashu2310/cartograph.git

uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# v2 needs the ty LSP binary on PATH (used by the resolver)
uv tool install ty

pre-commit install
```

## Running Tests

```bash
pytest                                 # v1 + v2 suites
pytest tests/ -m "not integration"     # v1 only, skip external-repo tests
pytest tests_v2/                       # v2 only
pytest -v tests_v2/test_pipeline.py    # single file
```

## Linting

```bash
ruff check cartograph/ tests/ tests_v2/
ruff format cartograph/ tests/ tests_v2/
```

Pre-commit hooks run ruff automatically on every commit.

## Project Structure

Cartograph has two parallel implementations during the v2 transition:

```
cartograph/
├── cli.py             # v1 CLI (carto / cartograph)
├── core.py            # v1: parse → build graph → discover
├── parser/            # v1: AST parser, language adapters, framework detectors
├── graph/             # v1: call graph builder, type inference, models
├── web/               # v1: FastAPI + ELK.js viewer
├── llm/               # v1: LLM providers + narrator
└── v2/                # v2 rewrite
    ├── cli/           # v2 CLI (carto2) — one file per command
    ├── analyses/      # one file per engineering-insight finding kind
    ├── pipeline.py    # 5-stage orchestrator
    ├── config.py      # RunConfig
    ├── cache/         # content-addressed caches (both stages)
    ├── ir/            # immutable pydantic IRs (syntactic / resolved / annotated / analyzed)
    ├── stages/
    │   ├── extract/   # tree-sitter parser → SyntacticModule
    │   ├── resolve/   # ty LSP client → ResolvedGraph
    │   ├── annotate/  # framework annotators → AnnotatedGraph
    │   ├── discover/  # topology entry-point finder → AnalyzedGraph
    │   └── present/   # CLI / web / LLM / markdown renderers
    ├── mcp/           # FastMCP server
    ├── benchmark/     # v1 ↔ v2 measurement rig
    └── web/           # v2: Cytoscape.js DAG viewer
```

## Extension Guide (v2)

Three extension points.

### 1. Adding an Analysis

One file per finding kind, under `cartograph/v2/analyses/`. A finding is a frozen pydantic IR; a `find_*` function yields them from an `AnalyzedGraph`.

**Files:** a new `analyses/_my_thing.py`, `analyses/__init__.py` (re-export + bundle), `cartograph/v2/cli/_render.py` (if it needs a Rich table in `analyze`), `tests_v2/test_analyses.py`.

```python
# analyses/_my_thing.py
class MyFinding(IR):
    qname: str
    detail: str

def find_my_thing(graph: AnalyzedGraph) -> Iterator[MyFinding]:
    for qname, ref in graph.annotated.resolved.functions.items():
        if _matches(ref):
            yield MyFinding(qname=qname, detail="...")
```

Re-export from `analyses/__init__.py`, add a tuple field to `AnalysisReport` (default `()`), wire `analyze()` to call `find_my_thing(graph)`. If framework-specific, gate on a project-wide import check — the ORM analyses do this via `_iter_orm_by_function`.

Canonical examples: `_cycles.py` (Tarjan over import edges), `_async_patterns.py` (curated blocking-hint table), `_routes.py` (group-by on `ApiRouteEntry`).

### 2. Adding a Framework Annotator

Discovery is topology-based by default. Annotators add richer labels (`GET /users` vs. `@router.get`) and promote `DiscoveredEntry` to `ApiRouteEntry` / `CeleryTaskEntry` / `SignalHandlerEntry`.

**Files:** new `stages/annotate/frameworks/<name>.py`, `stages/annotate/registry.py`, `ir/annotated.py`, `tests_v2/test_framework_annotators.py`.

1. Add your label as a discriminated-union member of `SemanticLabel` in `ir/annotated.py` (unique `kind` literal).
2. Implement the `Annotator` protocol (see `stages/annotate/protocol.py`):

    ```python
    class MyFrameworkAnnotator:
        framework = "my_framework"

        def annotate(self, graph, modules):
            out = {}
            # Type-resolved path: ty knows where the decorator points.
            for qname, decs in graph.decorators_by_target.items():
                label = _match_resolved(decs)
                if label:
                    out[qname] = (label,)
            # Syntactic fallback when resolution is empty.
            if not graph.decorators_by_target:
                ...
            return out
    ```

3. Register in `stages/annotate/registry.py::default_annotators()`.

Prefer the resolved-decorator path — it matches on `fastapi.APIRouter.get` instead of the syntactic `@router.get`, so aliases and re-exports work for free. Canonical example: `stages/annotate/frameworks/fastapi.py`.

### 3. Adding a Presenter / Output Format

Presenters consume `AnalyzedGraph` and produce output. Pure functions — no caching, no LSP, no framework work behind the stage boundary.

- **CLI:** add a command module under `cartograph/v2/cli/commands/` and, if needed, a Rich helper in `cli/_render.py`.
- **Web:** Cytoscape JSON in `stages/present/web_serializers.py`; endpoint in `web/app.py`; consumer in `web/static/index.html`.
- **Markdown (for piping to LLMs):** extend `stages/present/markdown.py`.
- **MCP:** add a tool to `mcp/server.py`. Keep the tool surface tight — an agent with thirty tools can't pick between them.

## Submitting a PR

```bash
git checkout -b my-change
# ...commit changes...
git push origin my-change
```

Open a PR via the GitHub UI: `<your-username>/cartograph:my-change` → `sashu2310/cartograph:main`.

Keep your fork synced:

```bash
git fetch upstream
git checkout main
git merge upstream/main
git push origin main
```
