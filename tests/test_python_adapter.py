"""Tests for the Python language adapter."""

import tempfile

from cartograph.graph.models import NodeType
from cartograph.parser.languages.python.adapter import PythonAdapter
from tests.conftest import FIXTURES_DIR, parse_fixture


class TestPythonAdapterParsing:
    def setup_method(self):
        self.adapter = PythonAdapter()

    def test_parse_simple_functions(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        assert module is not None
        assert module.module_path == "fixtures.simple_functions"
        assert len(module.functions) > 0

    def test_extracts_function_names(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        func_names = [f.name for f in module.functions]
        assert "hello" in func_names
        assert "process_data" in func_names
        assert "transform" in func_names

    def test_extracts_qualified_names(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        hello = next(f for f in module.functions if f.name == "hello")
        assert hello.qualified_name == "fixtures.simple_functions.hello"

    def test_extracts_class_and_methods(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        func_names = [f.name for f in module.functions]
        assert "DataProcessor" in func_names
        assert "DataProcessor.run" in func_names
        assert "DataProcessor.fetch_data" in func_names

    def test_class_methods_have_correct_type(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        run_method = next(f for f in module.functions if f.name == "DataProcessor.run")
        assert run_method.type == NodeType.METHOD
        assert run_method.class_name == "DataProcessor"

    def test_class_has_class_type(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        dp = next(f for f in module.functions if f.name == "DataProcessor")
        assert dp.type == NodeType.CLASS

    def test_extracts_docstrings(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        hello = next(f for f in module.functions if f.name == "hello")
        assert hello.docstring == "Say hello."

    def test_extracts_line_numbers(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        hello = next(f for f in module.functions if f.name == "hello")
        assert hello.line_start > 0
        assert hello.line_end >= hello.line_start

    def test_extracts_function_calls(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        transform = next(f for f in module.functions if f.name == "transform")
        call_names = [c.name for c in transform.calls]
        assert "get" in call_names
        assert "cleanup" in call_names

    def test_extracts_method_calls_with_receiver(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        transform = next(f for f in module.functions if f.name == "transform")
        get_call = next(c for c in transform.calls if c.name == "get")
        assert get_call.is_method_call
        assert get_call.receiver == "item"

    def test_extracts_conditional_branches(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        process = next(f for f in module.functions if f.name == "process_data")
        assert len(process.branches) > 0
        first_branch = process.branches[0]
        assert first_branch.condition is not None

    def test_extracts_imports(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        import_names = [i.name for i in module.imports]
        assert "os" in import_names
        assert "Path" in import_names

    def test_extracts_classes_list(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        assert "DataProcessor" in module.classes

    def test_file_hash_is_set(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        assert module.file_hash is not None
        assert len(module.file_hash) == 32  # MD5 hex

    def test_extracts_decorators(self):
        module = parse_fixture(self.adapter, "django_controller.py")
        eq_controller = next(
            f for f in module.functions if f.name == "EquipmentApiController"
        )
        assert "api_controller" in eq_controller.decorators

    def test_extracts_decorator_details(self):
        module = parse_fixture(self.adapter, "django_controller.py")
        eq_controller = next(
            f for f in module.functions if f.name == "EquipmentApiController"
        )
        assert len(eq_controller.decorator_details) > 0
        detail = eq_controller.decorator_details[0]
        assert detail["name"] == "api_controller"
        assert "/equipments" in detail["args"]


class TestPythonAdapterEdgeCases:
    def setup_method(self):
        self.adapter = PythonAdapter()

    def test_returns_none_for_nonexistent_file(self):
        result = self.adapter.parse_file("/nonexistent/file.py", "fake.module")
        assert result is None

    def test_returns_none_for_non_python_file(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w") as f:
            f.write("not python")
            f.flush()
            result = self.adapter.parse_file(f.name, "fake.module")
            assert result is None

    def test_returns_none_for_syntax_error(self):
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("def broken(\n")
            f.flush()
            result = self.adapter.parse_file(f.name, "fake.module")
            assert result is None

    def test_handles_empty_file(self):
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("")
            f.flush()
            result = self.adapter.parse_file(f.name, "empty_module")
            assert result is not None
            assert len(result.functions) == 0


class TestPythonAdapterImportResolution:
    def setup_method(self):
        self.adapter = PythonAdapter()

    def test_resolves_absolute_import(self):
        from cartograph.graph.models import ParsedImport

        imp = ParsedImport(module="fixtures.simple_functions", name="hello")
        resolved = self.adapter.resolve_import(
            imp, str(FIXTURES_DIR / "other.py"), str(FIXTURES_DIR.parent)
        )
        assert resolved is not None
        assert "simple_functions.py" in resolved

    def test_returns_none_for_unresolvable_import(self):
        from cartograph.graph.models import ParsedImport

        imp = ParsedImport(module="nonexistent.module", name="thing")
        resolved = self.adapter.resolve_import(
            imp, str(FIXTURES_DIR / "other.py"), str(FIXTURES_DIR.parent)
        )
        assert resolved is None
