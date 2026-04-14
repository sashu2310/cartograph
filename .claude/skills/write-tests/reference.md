# Test Conventions Reference

## Runner

```bash
pytest                          # All tests
pytest -m "not integration"     # Unit only
pytest -v tests/test_foo.py     # Single file
```

## Fixtures (tests/conftest.py)

```python
@pytest.fixture
def python_adapter():
    return PythonAdapter()

@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR  # Path("tests/fixtures")

def parse_fixture(adapter, filename):
    path = FIXTURES_DIR / filename
    return adapter.parse_file(path)
```

## Test Fixture Files

Located in `tests/fixtures/`. Add new `.py` fixture files here for new parsing scenarios.

Multifile tests use `tests/fixtures/multifile/` — a mini-project with `worker.py`, `processor.py`, `notifier.py`, `store.py`.

## Structure

Class-based grouping for related tests:

```python
class TestCallGraphBuilder:
    def test_resolves_direct_calls(self):
        ...

    def test_detects_async_boundary(self):
        ...
```

## Assertion Patterns

```python
# Parser tests — check extracted data
module = parse_fixture(python_adapter, "simple_functions.py")
names = [f.name for f in module.functions]
assert "process_data" in names

# Call graph tests — check edges
graph = builder.build(index)
callees = graph.get_callees("worker.process")
assert "processor.transform" in callees

# Entry point tests — check detection
entry_points = detector.detect_entry_points(module)
assert any(ep.type == EntryPointType.CELERY_TASK for ep in entry_points)

# Count assertions
assert len(module.functions) == 5
assert graph.total_resolved > 0
```

## Rules

- Test against real Python fixture files, not mocked AST
- Use `parse_fixture()` helper, not manual path construction
- Use `fixtures_dir` fixture for path references
- Add new fixtures to `tests/fixtures/` when testing new scenarios
- Mark slow/external tests with `@pytest.mark.integration`
