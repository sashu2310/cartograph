# Review Gaps Reference

Common patterns that have caused issues in this codebase, derived from git history.

## Call Resolution Edge Cases

The `CallGraphBuilder` resolves calls through imports and type inference. Common gaps:

- **Relative imports** — `from .models import Foo` must resolve correctly across packages
- **Re-exports** — `from cartograph.graph import models` vs `from cartograph.graph.models import Node`
- **Type inference** — `x = Foo()` → `x.method()` resolution depends on `local_types` tracking
- **Self methods** — `self.method()` must resolve within the correct class scope

## Framework Detector False Positives

- Celery: decorator detection must handle `@app.task` AND `@shared_task`, not just substring match
- Django Ninja: must distinguish `@api_controller` from `@api.get` patterns
- ORM: `filter()`, `get()`, `all()` are common method names — must check receiver is QuerySet/Manager

## Serialization Consistency

When models change:
- `cartograph/web/serializers.py` must handle new fields
- `cartograph/cli.py` JSON output (`_serialize_graph_trace`) must stay consistent
- Enum additions must be JSON-serializable (uses `str, Enum` pattern)

## Test Coverage Gaps

Watch for:
- New fixture file needed but not created
- Cross-file resolution test (`multifile/`) not updated for new import patterns
- Integration tests skipped locally but broken in full runs
