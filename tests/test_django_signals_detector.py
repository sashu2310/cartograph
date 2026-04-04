"""Tests for the Django signals framework detector."""

from cartograph.graph.models import EntryPointType, FunctionCall
from cartograph.parser.languages.python.adapter import PythonAdapter
from cartograph.parser.languages.python.frameworks.django_signals import (
    DjangoSignalDetector,
)
from tests.conftest import parse_fixture


class TestDjangoSignalDetector:
    def setup_method(self):
        self.adapter = PythonAdapter()
        self.detector = DjangoSignalDetector()

    def test_detects_receiver_as_entry_point(self):
        module = parse_fixture(self.adapter, "django_signals.py")
        entries = self.detector.detect_entry_points(module)
        assert len(entries) >= 2

    def test_entry_point_type_is_signal_handler(self):
        module = parse_fixture(self.adapter, "django_signals.py")
        entries = self.detector.detect_entry_points(module)
        for entry in entries:
            assert entry.type == EntryPointType.SIGNAL_HANDLER

    def test_trigger_includes_signal_info(self):
        module = parse_fixture(self.adapter, "django_signals.py")
        entries = self.detector.detect_entry_points(module)
        assert any("Signal" in e.trigger for e in entries)

    def test_annotates_connect_call(self):
        call = FunctionCall(name="connect", is_method_call=True, receiver="post_save")
        result = self.detector.annotate_call(call)
        assert result is not None
        assert result["signal_connection"] is True
        assert result["signal"] == "post_save"

    def test_annotates_send_call(self):
        call = FunctionCall(name="send", is_method_call=True, receiver="my_signal")
        result = self.detector.annotate_call(call)
        assert result is not None
        assert result["signal_emit"] is True

    def test_ignores_non_signal_calls(self):
        call = FunctionCall(name="save", is_method_call=True, receiver="obj")
        result = self.detector.annotate_call(call)
        assert result is None

    def test_ignores_non_signal_file(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        entries = self.detector.detect_entry_points(module)
        assert len(entries) == 0
