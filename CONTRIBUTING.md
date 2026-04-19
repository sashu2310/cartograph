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
    ├── cli.py         # v2 CLI (carto2)
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
    ├── benchmark/     # v1 ↔ v2 measurement rig
    └── web/           # v2: Cytoscape.js DAG viewer
```

## Adding a Framework Annotator (v2)

v2 uses topology-based discovery by default (decorator + zero-in-edges + some-out-edges ⇒ entry point). Dedicated annotators add richer labels ("GET /users" vs "@router.get").

1. Create `cartograph/v2/stages/annotate/frameworks/your_framework.py`
2. Implement the `Annotator` protocol (see `cartograph/v2/stages/annotate/protocol.py`) — one method, `annotate(resolved, modules_by_name) -> dict[qname, labels]`
3. Add your label variant to `cartograph/v2/ir/annotated.py` (discriminated-union member)
4. Register in `cartograph/v2/stages/annotate/registry.py` → `default_annotators()`
5. Fixture in `tests/fixtures/`, tests in `tests_v2/test_framework_annotators.py`

See `cartograph/v2/stages/annotate/frameworks/celery.py` for a complete example.

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
