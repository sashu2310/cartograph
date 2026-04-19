"""Tests for TreesitterExtractor."""

from __future__ import annotations

from pathlib import Path

from cartograph.v2.ir.base import is_err, is_ok
from cartograph.v2.ir.errors import IoExtractError
from cartograph.v2.ir.syntactic import AsyncDispatchCall, PlainCall
from cartograph.v2.stages.extract.treesitter_extractor import TreesitterExtractor

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _extract_ok(extractor, path, module_name):
    result = extractor.extract(path, module_name)
    assert is_ok(result), f"extract failed: {result}"
    return result.value


class TestTreesitterExtractor:
    def test_extracts_expected_functions(self):
        mod = _extract_ok(TreesitterExtractor(), FIXTURES / "simple_functions.py", "sf")
        names = {fn.name for fn in mod.functions}
        assert {"process_data", "transform", "cleanup", "log_error"} <= names

    def test_extracts_expected_classes(self):
        mod = _extract_ok(TreesitterExtractor(), FIXTURES / "simple_functions.py", "sf")
        class_names = {c.name for c in mod.classes}
        assert "DataProcessor" in class_names

    def test_imports_extracted(self):
        mod = _extract_ok(TreesitterExtractor(), FIXTURES / "simple_functions.py", "sf")
        import_modules = {imp.module for imp in mod.imports}
        assert "os" in import_modules
        assert "pathlib" in import_modules

    def test_decorators_with_args_captured(self):
        mod = _extract_ok(
            TreesitterExtractor(), FIXTURES / "celery_tasks.py", "celery_tasks"
        )
        process = next(fn for fn in mod.functions if fn.name == "process_sensor_data")
        assert "celery_app.task" in process.decorator_names
        task_dec = next(d for d in process.decorators if d.name == "celery_app.task")
        assert task_dec.kwargs.get("queue") == "server"

    def test_method_call_classification(self):
        mod = _extract_ok(TreesitterExtractor(), FIXTURES / "simple_functions.py", "sf")
        transform = next(fn for fn in mod.functions if fn.name == "transform")
        call_names = {cs.call.name for cs in transform.call_sites}
        assert "cleanup" in call_names
        assert "get" in call_names

    def test_async_dispatch_classification(self):
        mod = _extract_ok(
            TreesitterExtractor(), FIXTURES / "celery_tasks.py", "celery_tasks"
        )
        process = next(fn for fn in mod.functions if fn.name == "process_sensor_data")
        dispatches = [
            cs for cs in process.call_sites if isinstance(cs.call, AsyncDispatchCall)
        ]
        assert len(dispatches) >= 1
        assert any(d.call.dispatch_kind == "delay" for d in dispatches)

    def test_missing_file_returns_err(self, tmp_path):
        result = TreesitterExtractor().extract(tmp_path / "nope.py", "nope")
        assert is_err(result)
        assert isinstance(result.error, IoExtractError)

    def test_tolerates_broken_syntax(self, tmp_path):
        """The headline feature — tree-sitter shouldn't bail on partial syntax
        the way stdlib ast does."""
        broken = tmp_path / "broken.py"
        broken.write_text(
            "def good():\n    return 1\n\ndef broken(\n    # unfinished\n"
        )
        result = TreesitterExtractor().extract(broken, "broken")
        assert is_ok(result)
        good = next((fn for fn in result.value.functions if fn.name == "good"), None)
        assert good is not None, "well-formed function should be extracted"

    def test_docstring_captured(self, tmp_path):
        src = tmp_path / "doc.py"
        src.write_text(
            "def helper():\n"
            '    """Short."""\n'
            "    return 1\n"
            "\n"
            "def bare():\n"
            "    return 2\n"
            "\n"
            "async def fetch():\n"
            '    """Multi.\n'
            "\n"
            "    More.\n"
            '    """\n'
            "    return 3\n"
        )
        mod = _extract_ok(TreesitterExtractor(), src, "doc")
        by_name = {f.name: f for f in mod.functions}
        assert by_name["helper"].docstring == "Short."
        assert by_name["bare"].docstring is None
        assert by_name["fetch"].docstring.startswith("Multi.")

    def test_plain_call_positioning(self):
        mod = _extract_ok(TreesitterExtractor(), FIXTURES / "simple_functions.py", "sf")
        log_error = next(fn for fn in mod.functions if fn.name == "log_error")
        prints = [cs for cs in log_error.call_sites if cs.call.name == "print"]
        assert prints, "expected a print() call site"
        assert isinstance(prints[0].call, PlainCall)
