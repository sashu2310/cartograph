"""Tests for module-level instance import resolution.

Validates that imported service instances (e.g., `from .service import user_service`
where `user_service = UserService()`) resolve method calls to the class methods.
This is the dominant pattern in FastAPI/Django codebases like Polar.
"""

from pathlib import Path

from cartograph.graph.call_graph import CallGraphBuilder
from cartograph.graph.models import ProjectIndex
from cartograph.parser.languages.python.adapter import PythonAdapter

INSTANCE_DIR = Path(__file__).parent / "fixtures" / "instance_import"


def _build_instance_index() -> ProjectIndex:
    """Parse the instance_import fixtures into a ProjectIndex."""
    adapter = PythonAdapter()
    index = ProjectIndex(root_path=str(INSTANCE_DIR))

    for py_file in INSTANCE_DIR.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        relative = py_file.relative_to(INSTANCE_DIR)
        module_path = "fixtures.instance_import." + str(
            relative.with_suffix("")
        ).replace("/", ".")
        module = adapter.parse_file(str(py_file), module_path)
        if module:
            index.modules[module.module_path] = module

    return index


class TestModuleLevelTypeTracking:
    def test_tracks_module_level_instance(self):
        adapter = PythonAdapter()
        module = adapter.parse_file(
            str(INSTANCE_DIR / "service.py"), "fixtures.instance_import.service"
        )
        assert "user_service" in module.module_types
        assert module.module_types["user_service"] == "UserService"

    def test_does_not_track_function_level_assignments(self):
        """Module types should only contain module-level assignments."""
        adapter = PythonAdapter()
        module = adapter.parse_file(
            str(INSTANCE_DIR / "endpoints.py"), "fixtures.instance_import.endpoints"
        )
        # endpoints.py has no module-level instance creation
        assert len(module.module_types) == 0


class TestInstanceImportResolution:
    def setup_method(self):
        self.index = _build_instance_index()
        builder = CallGraphBuilder(self.index)
        self.graph = builder.build()

    def test_resolves_instance_method_call(self):
        """user_service.get_user() should resolve to UserService.get_user."""
        edges = [
            e
            for e in self.graph.edges
            if "get_user_endpoint" in e.caller and "get_user" in e.callee
        ]
        assert len(edges) >= 1
        assert "UserService.get_user" in edges[0].callee

    def test_resolves_create_method(self):
        """user_service.create_user() should resolve to UserService.create_user."""
        edges = [
            e
            for e in self.graph.edges
            if "create_user_endpoint" in e.caller and "create_user" in e.callee
        ]
        assert len(edges) >= 1
        assert "UserService.create_user" in edges[0].callee

    def test_resolves_delete_method(self):
        """user_service.delete_user() should resolve to UserService.delete_user."""
        edges = [
            e
            for e in self.graph.edges
            if "delete_user_endpoint" in e.caller and "delete_user" in e.callee
        ]
        assert len(edges) >= 1
        assert "UserService.delete_user" in edges[0].callee

    def test_cross_file_edges(self):
        """Instance method calls should be marked as cross-file."""
        cross_file = [
            e
            for e in self.graph.edges
            if "endpoint" in e.caller and "UserService" in e.callee
        ]
        assert all(e.is_cross_file for e in cross_file)

    def test_service_internal_calls_resolve(self):
        """UserService.get_user calls find_user (same module)."""
        edges = [
            e
            for e in self.graph.edges
            if "UserService.get_user" in e.caller and "find_user" in e.callee
        ]
        assert len(edges) >= 1

    def test_chained_resolution(self):
        """endpoint → service.method → helper should form a chain."""
        # get_user_endpoint → UserService.get_user
        hop1 = [
            e
            for e in self.graph.edges
            if "get_user_endpoint" in e.caller and "UserService.get_user" in e.callee
        ]
        # UserService.get_user → find_user
        hop2 = [
            e
            for e in self.graph.edges
            if "UserService.get_user" in e.caller and "find_user" in e.callee
        ]
        assert len(hop1) >= 1
        assert len(hop2) >= 1
