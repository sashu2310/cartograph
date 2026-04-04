"""Tests for the language and framework registries."""

from cartograph.graph.models import (
    AsyncBoundaryType,
    FunctionCall,
    ParsedFunction,
    ParsedModule,
)
from cartograph.parser.languages.python.adapter import PythonAdapter
from cartograph.parser.languages.python.frameworks.celery import CeleryDetector
from cartograph.parser.languages.python.frameworks.django_ninja import (
    DjangoNinjaDetector,
)
from cartograph.parser.registry import FrameworkRegistry, LanguageRegistry


class TestLanguageRegistry:
    def test_registers_adapter_by_extension(self):
        registry = LanguageRegistry()
        adapter = PythonAdapter()
        registry.register(adapter)
        assert ".py" in registry.supported_extensions

    def test_returns_adapter_for_py_file(self):
        registry = LanguageRegistry()
        registry.register(PythonAdapter())
        adapter = registry.get_adapter("path/to/file.py")
        assert adapter is not None
        assert adapter.language_id == "python"

    def test_returns_none_for_unknown_extension(self):
        registry = LanguageRegistry()
        registry.register(PythonAdapter())
        adapter = registry.get_adapter("path/to/file.java")
        assert adapter is None

    def test_returns_none_for_empty_registry(self):
        registry = LanguageRegistry()
        adapter = registry.get_adapter("file.py")
        assert adapter is None

    def test_get_by_language(self):
        registry = LanguageRegistry()
        registry.register(PythonAdapter())
        adapter = registry.get_by_language("python")
        assert adapter is not None

    def test_supported_languages(self):
        registry = LanguageRegistry()
        registry.register(PythonAdapter())
        assert "python" in registry.supported_languages


class TestFrameworkRegistry:
    def test_registers_detector(self):
        registry = FrameworkRegistry()
        registry.register("python", CeleryDetector())
        detectors = registry.get_detectors("python")
        assert len(detectors) == 1

    def test_registers_multiple_detectors(self):
        registry = FrameworkRegistry()
        registry.register("python", CeleryDetector())
        registry.register("python", DjangoNinjaDetector())
        detectors = registry.get_detectors("python")
        assert len(detectors) == 2

    def test_returns_empty_for_unknown_language(self):
        registry = FrameworkRegistry()
        registry.register("python", CeleryDetector())
        detectors = registry.get_detectors("java")
        assert len(detectors) == 0

    def test_annotate_module_marks_async_boundaries(self):
        registry = FrameworkRegistry()
        registry.register("python", CeleryDetector())

        delay_call = FunctionCall(name="delay", is_method_call=True, receiver="my_task")
        func = ParsedFunction(
            name="test_func",
            qualified_name="test.test_func",
            file_path="test.py",
            line_start=1,
            line_end=5,
            calls=[delay_call],
        )
        module = ParsedModule(
            file_path="test.py",
            module_path="test",
            functions=[func],
        )

        registry.annotate_module(module, "python")

        assert delay_call.is_async_dispatch is True
        assert delay_call.async_type == AsyncBoundaryType.CELERY_DELAY
