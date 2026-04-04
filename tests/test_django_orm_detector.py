"""Tests for the Django ORM operation detector."""

from cartograph.graph.models import FunctionCall
from cartograph.parser.languages.python.frameworks.django_orm import DjangoORMDetector


class TestDjangoORMDetector:
    def setup_method(self):
        self.detector = DjangoORMDetector()

    def test_annotates_filter_as_read(self):
        call = FunctionCall(
            name="filter", is_method_call=True, receiver="Sensor.objects"
        )
        result = self.detector.annotate_call(call)
        assert result is not None
        assert result["orm_operation"] == "read"
        assert result["model"] == "Sensor"

    def test_annotates_get_as_read(self):
        call = FunctionCall(
            name="get", is_method_call=True, receiver="Equipment.objects"
        )
        result = self.detector.annotate_call(call)
        assert result["orm_operation"] == "read"
        assert result["model"] == "Equipment"

    def test_annotates_all_as_read(self):
        call = FunctionCall(name="all", is_method_call=True, receiver="Sensor.objects")
        result = self.detector.annotate_call(call)
        assert result["orm_operation"] == "read"

    def test_annotates_create_as_write(self):
        call = FunctionCall(
            name="create", is_method_call=True, receiver="Sensor.objects"
        )
        result = self.detector.annotate_call(call)
        assert result["orm_operation"] == "write"
        assert result["model"] == "Sensor"

    def test_annotates_save_as_write(self):
        call = FunctionCall(name="save", is_method_call=True, receiver="sensor")
        result = self.detector.annotate_call(call)
        assert result["orm_operation"] == "write"

    def test_annotates_bulk_create_as_write(self):
        call = FunctionCall(
            name="bulk_create", is_method_call=True, receiver="Equipment.objects"
        )
        result = self.detector.annotate_call(call)
        assert result["orm_operation"] == "write"
        assert result["model"] == "Equipment"

    def test_annotates_delete_as_delete(self):
        call = FunctionCall(name="delete", is_method_call=True, receiver="sensor")
        result = self.detector.annotate_call(call)
        assert result["orm_operation"] == "delete"

    def test_extracts_model_from_objects_manager(self):
        call = FunctionCall(
            name="filter", is_method_call=True, receiver="DiagnosticNode.objects"
        )
        result = self.detector.annotate_call(call)
        assert result["model"] == "DiagnosticNode"

    def test_ignores_non_orm_method(self):
        call = FunctionCall(name="append", is_method_call=True, receiver="results")
        result = self.detector.annotate_call(call)
        assert result is None

    def test_ignores_plain_function(self):
        call = FunctionCall(name="print", is_method_call=False)
        result = self.detector.annotate_call(call)
        assert result is None

    def test_no_entry_points(self):
        from cartograph.parser.languages.python.adapter import PythonAdapter
        from tests.conftest import parse_fixture

        adapter = PythonAdapter()
        module = parse_fixture(adapter, "orm_operations.py")
        entries = self.detector.detect_entry_points(module)
        assert len(entries) == 0
