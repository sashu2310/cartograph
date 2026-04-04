"""Tests for the Celery framework detector."""

from cartograph.graph.models import AsyncBoundaryType, EntryPointType, FunctionCall
from cartograph.parser.languages.python.adapter import PythonAdapter
from cartograph.parser.languages.python.frameworks.celery import CeleryDetector
from tests.conftest import parse_fixture


class TestCeleryEntryPoints:
    def setup_method(self):
        self.adapter = PythonAdapter()
        self.detector = CeleryDetector()

    def test_detects_celery_app_task(self):
        module = parse_fixture(self.adapter, "celery_tasks.py")
        entries = self.detector.detect_entry_points(module)
        entry_names = [e.node_id for e in entries]
        assert any("process_sensor_data" in name for name in entry_names)

    def test_detects_shared_task(self):
        module = parse_fixture(self.adapter, "celery_tasks.py")
        entries = self.detector.detect_entry_points(module)
        entry_names = [e.node_id for e in entries]
        assert any("validate_data" in name for name in entry_names)

    def test_entry_point_type_is_celery_task(self):
        module = parse_fixture(self.adapter, "celery_tasks.py")
        entries = self.detector.detect_entry_points(module)
        for entry in entries:
            assert entry.type == EntryPointType.CELERY_TASK

    def test_extracts_queue_from_decorator(self):
        module = parse_fixture(self.adapter, "celery_tasks.py")
        entries = self.detector.detect_entry_points(module)
        server_task = next(e for e in entries if "process_sensor_data" in e.node_id)
        assert "queue=server" in server_task.trigger

    def test_ignores_non_celery_decorators(self):
        module = parse_fixture(self.adapter, "django_controller.py")
        entries = self.detector.detect_entry_points(module)
        assert len(entries) == 0


class TestCeleryAsyncBoundaries:
    def setup_method(self):
        self.detector = CeleryDetector()

    def test_detects_delay(self):
        call = FunctionCall(name="delay", is_method_call=True, receiver="some_task")
        result = self.detector.detect_async_boundary(call)
        assert result == AsyncBoundaryType.CELERY_DELAY

    def test_detects_apply_async(self):
        call = FunctionCall(name="apply_async", is_method_call=True, receiver="task")
        result = self.detector.detect_async_boundary(call)
        assert result == AsyncBoundaryType.CELERY_APPLY_ASYNC

    def test_detects_chain(self):
        call = FunctionCall(name="chain", is_method_call=False)
        result = self.detector.detect_async_boundary(call)
        assert result == AsyncBoundaryType.CELERY_CHAIN

    def test_detects_chord(self):
        call = FunctionCall(name="chord", is_method_call=False)
        result = self.detector.detect_async_boundary(call)
        assert result == AsyncBoundaryType.CELERY_CHORD

    def test_detects_group(self):
        call = FunctionCall(name="group", is_method_call=False)
        result = self.detector.detect_async_boundary(call)
        assert result == AsyncBoundaryType.CELERY_GROUP

    def test_detects_s_signature(self):
        call = FunctionCall(name="s", is_method_call=True, receiver="my_task")
        result = self.detector.detect_async_boundary(call)
        assert result == AsyncBoundaryType.CELERY_DELAY

    def test_detects_si_signature(self):
        call = FunctionCall(name="si", is_method_call=True, receiver="my_task")
        result = self.detector.detect_async_boundary(call)
        assert result == AsyncBoundaryType.CELERY_DELAY

    def test_ignores_regular_method(self):
        call = FunctionCall(name="append", is_method_call=True, receiver="results")
        result = self.detector.detect_async_boundary(call)
        assert result is None

    def test_ignores_regular_function(self):
        call = FunctionCall(name="print", is_method_call=False)
        result = self.detector.detect_async_boundary(call)
        assert result is None
