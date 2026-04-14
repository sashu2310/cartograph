"""Tests for the Flask framework detector."""

from cartograph.graph.models import EntryPointType
from cartograph.parser.languages.python.adapter import PythonAdapter
from cartograph.parser.languages.python.frameworks.flask import FlaskDetector
from tests.conftest import parse_fixture


class TestFlaskDetector:
    def setup_method(self):
        self.adapter = PythonAdapter()
        self.detector = FlaskDetector()

    def test_detects_app_route(self):
        module = parse_fixture(self.adapter, "flask_app.py")
        entries = self.detector.detect_entry_points(module)
        route_entries = [e for e in entries if e.trigger.startswith("ROUTE")]
        assert len(route_entries) >= 2

    def test_detects_app_route_path(self):
        module = parse_fixture(self.adapter, "flask_app.py")
        entries = self.detector.detect_entry_points(module)
        home = next((e for e in entries if e.trigger == "ROUTE /"), None)
        assert home is not None

    def test_detects_app_get_shorthand(self):
        module = parse_fixture(self.adapter, "flask_app.py")
        entries = self.detector.detect_entry_points(module)
        get_routes = [e for e in entries if e.trigger.startswith("GET")]
        assert len(get_routes) >= 1

    def test_detects_app_post_shorthand(self):
        module = parse_fixture(self.adapter, "flask_app.py")
        entries = self.detector.detect_entry_points(module)
        post_routes = [e for e in entries if e.trigger.startswith("POST")]
        assert len(post_routes) >= 1

    def test_detects_app_delete_shorthand(self):
        module = parse_fixture(self.adapter, "flask_app.py")
        entries = self.detector.detect_entry_points(module)
        delete_routes = [e for e in entries if e.trigger.startswith("DELETE")]
        assert len(delete_routes) >= 1

    def test_detects_blueprint_route(self):
        module = parse_fixture(self.adapter, "flask_app.py")
        entries = self.detector.detect_entry_points(module)
        bp_route = next((e for e in entries if "list_users" in e.node_id), None)
        assert bp_route is not None
        assert bp_route.trigger.startswith("ROUTE")

    def test_detects_blueprint_get(self):
        module = parse_fixture(self.adapter, "flask_app.py")
        entries = self.detector.detect_entry_points(module)
        bp_get = next((e for e in entries if "get_user" in e.node_id), None)
        assert bp_get is not None
        assert bp_get.trigger.startswith("GET")

    def test_detects_blueprint_post(self):
        module = parse_fixture(self.adapter, "flask_app.py")
        entries = self.detector.detect_entry_points(module)
        bp_post = next((e for e in entries if "create_user" in e.node_id), None)
        assert bp_post is not None
        assert bp_post.trigger.startswith("POST")

    def test_detects_blueprint_put(self):
        module = parse_fixture(self.adapter, "flask_app.py")
        entries = self.detector.detect_entry_points(module)
        bp_put = next((e for e in entries if "update_user" in e.node_id), None)
        assert bp_put is not None
        assert bp_put.trigger.startswith("PUT")

    def test_detects_error_handler(self):
        module = parse_fixture(self.adapter, "flask_app.py")
        entries = self.detector.detect_entry_points(module)
        error_handlers = [e for e in entries if e.trigger.startswith("ERROR")]
        assert len(error_handlers) >= 2

    def test_error_handler_extracts_code(self):
        module = parse_fixture(self.adapter, "flask_app.py")
        entries = self.detector.detect_entry_points(module)
        e404 = next((e for e in entries if e.trigger == "ERROR 404"), None)
        assert e404 is not None

    def test_entry_point_type_is_api_route(self):
        module = parse_fixture(self.adapter, "flask_app.py")
        entries = self.detector.detect_entry_points(module)
        for entry in entries:
            assert entry.type == EntryPointType.API_ROUTE

    def test_preserves_docstring(self):
        module = parse_fixture(self.adapter, "flask_app.py")
        entries = self.detector.detect_entry_points(module)
        documented = [e for e in entries if e.description]
        assert len(documented) >= 1

    def test_ignores_non_flask_file(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        entries = self.detector.detect_entry_points(module)
        assert len(entries) == 0

    def test_total_entry_points(self):
        module = parse_fixture(self.adapter, "flask_app.py")
        entries = self.detector.detect_entry_points(module)
        # 3 app.route + 3 app shorthand + 4 blueprint + 2 errorhandler = 12
        assert len(entries) == 12
