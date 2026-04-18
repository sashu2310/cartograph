# Contributing to Cartograph

## Setup

```bash
git clone https://github.com/sashu2310/cartograph.git
cd cartograph
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest ruff pre-commit
pre-commit install
```

## Running Tests

```bash
pytest                          # all tests
pytest -m "not integration"     # skip tests requiring external repos
pytest -v tests/test_call_graph.py  # single file
```

## Linting

```bash
ruff check cartograph/ tests/
ruff format cartograph/ tests/
```

Pre-commit hooks run ruff automatically on every commit.

## Project Structure

```
cartograph/
├── parser/          # AST parsing, language adapters, framework detectors
├── graph/           # Call graph builder, type resolution, data models
├── cache/           # Persistent JSON cache (.cartograph/)
├── llm/             # LLM providers (Claude, OpenAI, Ollama)
├── web/             # FastAPI web viewer
├── cli.py           # Click CLI (scan, trace, entries, context, etc.)
├── core.py          # Pipeline: parse → build graph → discover entry points
└── config.py        # Configuration
```

## Adding a Framework Detector

Framework detectors are optional — topology-based discovery handles most cases. But detectors add rich labels ("GET /api/users" instead of "@router.get").

1. Create `cartograph/parser/languages/python/frameworks/your_framework.py`
2. Implement `detect_entry_points()`, `detect_async_boundary()`, `annotate_call()`
3. Register in `cartograph/parser/languages/python/frameworks/__init__.py`
4. Register in `cartograph/core.py` → `build_registries()`
5. Add test fixture in `tests/fixtures/` and tests in `tests/`

See `fastapi.py` or `flask.py` for examples.

## Adding a Language

1. Create `cartograph/parser/languages/your_lang/adapter.py`
2. Implement the `LanguageAdapter` protocol (see `cartograph/parser/protocols.py`)
3. Register in `cartograph/core.py` → `build_registries()`

The graph layer, CLI, and web viewer are language-agnostic — they don't change.
