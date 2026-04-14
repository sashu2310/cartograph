"""Tests for the FastAPI framework detector."""

from cartograph.graph.models import EntryPointType
from cartograph.parser.languages.python.adapter import PythonAdapter
from cartograph.parser.languages.python.frameworks.fastapi import FastAPIDetector
from tests.conftest import parse_fixture


class TestFastAPIDetector:
    def setup_method(self):
        self.adapter = PythonAdapter()
        self.detector = FastAPIDetector()

    def test_detects_app_get_routes(self):
        module = parse_fixture(self.adapter, "fastapi_app.py")
        entries = self.detector.detect_entry_points(module)
        get_routes = [e for e in entries if e.trigger.startswith("GET")]
        assert len(get_routes) >= 2

    def test_detects_app_post_route(self):
        module = parse_fixture(self.adapter, "fastapi_app.py")
        entries = self.detector.detect_entry_points(module)
        post_routes = [e for e in entries if e.trigger.startswith("POST")]
        assert len(post_routes) >= 1

    def test_detects_app_put_route(self):
        module = parse_fixture(self.adapter, "fastapi_app.py")
        entries = self.detector.detect_entry_points(module)
        put_routes = [e for e in entries if e.trigger.startswith("PUT")]
        assert len(put_routes) >= 1

    def test_detects_app_delete_route(self):
        module = parse_fixture(self.adapter, "fastapi_app.py")
        entries = self.detector.detect_entry_points(module)
        delete_routes = [e for e in entries if e.trigger.startswith("DELETE")]
        assert len(delete_routes) >= 1

    def test_detects_router_routes(self):
        module = parse_fixture(self.adapter, "fastapi_app.py")
        entries = self.detector.detect_entry_points(module)
        product_routes = [e for e in entries if "/products" in e.trigger]
        assert len(product_routes) >= 2

    def test_detects_router_patch(self):
        module = parse_fixture(self.adapter, "fastapi_app.py")
        entries = self.detector.detect_entry_points(module)
        patch_routes = [e for e in entries if e.trigger.startswith("PATCH")]
        assert len(patch_routes) >= 1

    def test_detects_websocket_route(self):
        module = parse_fixture(self.adapter, "fastapi_app.py")
        entries = self.detector.detect_entry_points(module)
        ws_routes = [e for e in entries if e.trigger.startswith("WS")]
        assert len(ws_routes) >= 1

    def test_extracts_path(self):
        module = parse_fixture(self.adapter, "fastapi_app.py")
        entries = self.detector.detect_entry_points(module)
        user_list = next((e for e in entries if e.trigger == "GET /users"), None)
        assert user_list is not None

    def test_extracts_path_with_parameter(self):
        module = parse_fixture(self.adapter, "fastapi_app.py")
        entries = self.detector.detect_entry_points(module)
        user_detail = next(
            (e for e in entries if e.trigger == "GET /users/{user_id}"), None
        )
        assert user_detail is not None

    def test_entry_point_type_is_api_route(self):
        module = parse_fixture(self.adapter, "fastapi_app.py")
        entries = self.detector.detect_entry_points(module)
        for entry in entries:
            assert entry.type == EntryPointType.API_ROUTE

    def test_preserves_docstring(self):
        module = parse_fixture(self.adapter, "fastapi_app.py")
        entries = self.detector.detect_entry_points(module)
        documented = [e for e in entries if e.description]
        assert len(documented) >= 1

    def test_ignores_non_fastapi_file(self):
        module = parse_fixture(self.adapter, "simple_functions.py")
        entries = self.detector.detect_entry_points(module)
        assert len(entries) == 0

    def test_total_entry_points(self):
        module = parse_fixture(self.adapter, "fastapi_app.py")
        entries = self.detector.detect_entry_points(module)
        # 5 app routes + 3 router routes + 1 websocket = 9
        assert len(entries) == 9
