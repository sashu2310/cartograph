"""Tests for the Django Ninja framework detector."""

from cartograph.graph.models import EntryPointType
from cartograph.parser.languages.python.adapter import PythonAdapter
from cartograph.parser.languages.python.frameworks.django_ninja import (
    DjangoNinjaDetector,
)
from tests.conftest import parse_fixture


class TestDjangoNinjaDetector:
    def setup_method(self):
        self.adapter = PythonAdapter()
        self.detector = DjangoNinjaDetector()

    def test_detects_api_controller(self):
        module = parse_fixture(self.adapter, "django_controller.py")
        entries = self.detector.detect_entry_points(module)
        controller_entries = [e for e in entries if "Controller:" in e.trigger]
        assert len(controller_entries) >= 1

    def test_extracts_url_prefix(self):
        module = parse_fixture(self.adapter, "django_controller.py")
        entries = self.detector.detect_entry_points(module)
        eq_controller = next((e for e in entries if "/equipments" in e.trigger), None)
        assert eq_controller is not None

    def test_detects_route_get(self):
        module = parse_fixture(self.adapter, "django_controller.py")
        entries = self.detector.detect_entry_points(module)
        get_routes = [e for e in entries if e.trigger.startswith("GET")]
        assert len(get_routes) >= 1

    def test_detects_route_post(self):
        module = parse_fixture(self.adapter, "django_controller.py")
        entries = self.detector.detect_entry_points(module)
        post_routes = [e for e in entries if e.trigger.startswith("POST")]
        assert len(post_routes) >= 1

    def test_detects_route_delete(self):
        module = parse_fixture(self.adapter, "django_controller.py")
        entries = self.detector.detect_entry_points(module)
        delete_routes = [e for e in entries if e.trigger.startswith("DELETE")]
        assert len(delete_routes) >= 1

    def test_entry_point_type_is_api_route(self):
        module = parse_fixture(self.adapter, "django_controller.py")
        entries = self.detector.detect_entry_points(module)
        for entry in entries:
            assert entry.type == EntryPointType.API_ROUTE

    def test_ignores_non_django_file(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        entries = self.detector.detect_entry_points(module)
        assert len(entries) == 0
