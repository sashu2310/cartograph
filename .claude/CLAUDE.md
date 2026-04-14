# CLAUDE.md — CARTOGRAPH

## Project Overview

CARTOGRAPH is a static analysis tool that parses Python codebases into call graphs with cross-file import resolution, framework-aware entry point detection, and optional LLM-powered flow narration. Outputs interactive DAGs via CLI (Rich) or web viewer (FastAPI). Open source, MIT licensed.

**Repo:** https://github.com/sashu2310/cartograph
**Author:** Sandeep Kesarwani <sandeepkesar2310@gmail.com>

## Commands

### Development

```bash
# Install (editable)
pip install -e .

# Run CLI commands
cartograph init /path/to/project [--include-tests]
cartograph trace /path/to/project "function_name" [-d DEPTH] [-o output.json]
cartograph summary /path/to/project
cartograph serve /path/to/project [-p 3333] [--host 0.0.0.0]
cartograph explain /path/to/project "function_name" [-d DEPTH]
```

### Testing

```bash
pytest                              # All tests
pytest -m "not integration"         # Skip real-world project tests
pytest -v tests/test_call_graph.py  # Specific test file
```

### Linting

```bash
ruff check cartograph/ tests/      # Lint
ruff check cartograph/ tests/ --fix # Lint + autofix
ruff format cartograph/ tests/      # Format
```

## Architecture

**Three-layer parser pipeline:**

```
Layer 1: Syntax Parser     — stdlib ast (Python), Tree-sitter (future)
Layer 2: Language Adapter   — one per language, outputs ParsedModule IR
Layer 3: Framework Detector — one per framework, annotates IR with semantic meaning
```

**Module map:**

| Module | Purpose |
|--------|---------|
| `cartograph/parser/protocols.py` | `LanguageAdapter` and `FrameworkDetector` protocol contracts |
| `cartograph/parser/registry.py` | Extension → adapter mapping, framework detector orchestration |
| `cartograph/parser/languages/python/adapter.py` | `PythonAdapter` — AST-based parser, `_CallExtractor` visitor |
| `cartograph/parser/languages/python/frameworks/` | Celery, Django Ninja, Django ORM, Django Signals detectors |
| `cartograph/graph/models.py` | `ParsedModule`, `ParsedFunction`, `ProjectIndex`, `EntryPoint`, enums |
| `cartograph/graph/call_graph.py` | `CallGraphBuilder` — import resolution, type inference, `CallGraph` |
| `cartograph/core.py` | `parse_project()`, `parse_and_build()` — top-level pipeline |
| `cartograph/config.py` | `CartographConfig` dataclass, `DEFAULT_EXCLUDE_DIRS` |
| `cartograph/cli.py` | Click CLI — `init`, `trace`, `summary`, `serve`, `explain` |
| `cartograph/web/app.py` | FastAPI app factory, REST endpoints for web viewer |
| `cartograph/web/serializers.py` | JSON serializers for overview, graph trace, callers, search |
| `cartograph/llm/provider.py` | LLM provider abstraction — Claude, OpenAI, Ollama |
| `cartograph/llm/narrator.py` | Flow narration pipeline (graph + source → LLM → narrative) |
| `cartograph/llm/prompts.py` | System/user prompt templates for narration |

**Key data flow:**

```
Files → PythonAdapter.parse_file() → ParsedModule
ParsedModules → FrameworkDetectors → annotated ParsedModules
ParsedModules → CallGraphBuilder.build() → CallGraph (edges, unresolved)
CallGraph → CLI trace / Web API / LLM narrator
```

## Settings & Environment

**LLM configuration (env vars):**

| Variable | Values | Default |
|----------|--------|---------|
| `CARTOGRAPH_LLM_PROVIDER` | `claude`, `openai`, `ollama` | `claude` |
| `CARTOGRAPH_LLM_MODEL` | Any model ID | Provider default |
| `ANTHROPIC_API_KEY` | API key | Required for Claude |
| `OPENAI_API_KEY` | API key | Required for OpenAI |
| `OLLAMA_HOST` | URL | `http://localhost:11434` |

No database. No dev/staging/prod split. Local-only tool.

## Git

- Remote: `git@github.com-personal:sashu2310/cartograph.git` (SSH via personal key)
- User: `sandeepkesar2310@gmail.com`
- Do NOT include Co-Authored-By or AI attribution in commits
- Pre-commit hooks: ruff lint + format (`.pre-commit-config.yaml`)

## Rules

- @rules/code-style.md
- @rules/testing.md
- @rules/api-patterns.md
