# Testing

## Runner

pytest 8.0+. Config in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["integration: tests that require external project clones"]
```

## Running Tests

```bash
pytest                              # All tests
pytest -m "not integration"         # Unit tests only
pytest -v tests/test_call_graph.py  # Single file
pytest -k "test_resolve"            # Name match
```

## Fixtures

Defined in `tests/conftest.py`:

```python
@pytest.fixture
def python_adapter():
    return PythonAdapter()

@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR  # tests/fixtures/

def parse_fixture(adapter, filename):
    """Parse a fixture file and return ParsedModule."""
    path = FIXTURES_DIR / filename
    return adapter.parse_file(path)
```

## Test Fixture Files

Located in `tests/fixtures/`:

| File | Purpose |
|------|---------|
| `simple_functions.py` | Basic functions, classes, methods, branches |
| `chained_calls.py` | Multi-level call chains |
| `celery_tasks.py` | Celery task definitions and async dispatches |
| `django_controller.py` | Django Ninja API endpoints |
| `django_signals.py` | Django signal handlers |
| `orm_operations.py` | Django ORM operations |
| `multifile/` | Cross-file import resolution (worker, processor, notifier, store) |

## Test Patterns

**Adapter tests** — parse fixture, assert on extracted data:

```python
class TestPythonAdapterParsing:
    def test_parses_function_names(self, python_adapter, fixtures_dir):
        module = parse_fixture(python_adapter, "simple_functions.py")
        names = [f.name for f in module.functions]
        assert "process_data" in names
```

**Call graph tests** — build index, build graph, assert edges:

```python
class TestCallGraphBuilder:
    def test_cross_file_resolution(self):
        index = build_project_index(modules)
        builder = CallGraphBuilder()
        graph = builder.build(index)
        callees = graph.get_callees("worker.process")
        assert "processor.transform" in callees
```

**Framework detector tests** — parse fixture, run detector, check entry points:

```python
def test_celery_task_detection(self, python_adapter):
    module = parse_fixture(python_adapter, "celery_tasks.py")
    detector = CeleryDetector()
    entry_points = detector.detect_entry_points(module)
    assert any(ep.type == EntryPointType.CELERY_TASK for ep in entry_points)
```

## Integration Tests

Marked `@pytest.mark.integration`. Require local clones of Celery, Kombu, Prefect in sibling directories. Skip with `-m "not integration"`.

## Always

- Add test fixtures in `tests/fixtures/` for new parsing scenarios.
- Use `parse_fixture()` helper instead of manually constructing paths.
- Use class-based test grouping (`TestXxxYyy`) for related tests.

## Never

- Don't mock the AST parser — test against real Python files.
- Don't hardcode absolute paths in tests — use `fixtures_dir` fixture.
