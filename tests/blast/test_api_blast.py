"""Tests for POST /api/blast endpoint — AC-8, AC-9, AC-12."""

from pathlib import Path

from fastapi.testclient import TestClient

from cartograph.graph.call_graph import CallGraphBuilder
from cartograph.web.app import create_app

MULTIFILE_DIR = Path(__file__).parent.parent / "fixtures" / "multifile"
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

_EXPECTED_RESPONSE_KEYS = {
    "input_kind",
    "changed_files",
    "changed_functions",
    "affected_functions",
    "affected_entry_points",
    "affected_tests",
    "stats",
}


def _make_test_client(project_dir: Path) -> TestClient:
    """Build a TestClient from a real project directory."""
    from cartograph.graph.models import ProjectIndex
    from cartograph.parser.languages.python.adapter import PythonAdapter

    adapter = PythonAdapter()
    index = ProjectIndex(root_path=str(project_dir))
    for py_file in project_dir.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        relative = py_file.relative_to(project_dir)
        module_path = "fixtures." + str(relative.with_suffix("")).replace("/", ".")
        module = adapter.parse_file(str(py_file), module_path)
        if module:
            index.modules[module.module_path] = module

    graph = CallGraphBuilder(index).build()
    app = create_app(graph=graph, index=index, project_name="test")
    return TestClient(app)


class TestApiBlastEndpointRegistered:
    # Spec: Section 9, assertion #7 — "POST /api/blast route registered in create_app()"

    def test_blast_route_exists_in_app(self):
        # Spec: Section 9, assertion #7 — "app.routes includes /api/blast with POST"
        from cartograph.graph.call_graph import CallGraph
        from cartograph.graph.models import ProjectIndex

        app = create_app(
            graph=CallGraph(),
            index=ProjectIndex(root_path="/tmp"),
            project_name="test",
        )
        blast_routes = [
            r for r in app.routes if hasattr(r, "path") and r.path == "/api/blast"
        ]
        assert len(blast_routes) > 0, "No route with path /api/blast found"
        blast_route = blast_routes[0]
        assert "POST" in blast_route.methods, (
            f"/api/blast route does not accept POST. Methods: {blast_route.methods}"
        )


class TestApiBlastHttp200:
    # Spec: Section 7, Criterion #12 — "POST /api/blast returns HTTP 200 with valid body"

    def test_post_blast_with_file_returns_200(self):
        # Spec: Section 7, Criterion #12 — "HTTP 200 on valid files request"
        client = _make_test_client(MULTIFILE_DIR)
        response = client.post(
            "/api/blast",
            json={"files": ["processor.py"], "functions": [], "depth": 10},
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}. Body:\n{response.text}"
        )

    def test_post_blast_response_has_correct_keys(self):
        # Spec: Section 7, Criterion #12 — "body matches Section 6 schema"
        client = _make_test_client(MULTIFILE_DIR)
        response = client.post(
            "/api/blast",
            json={"files": ["processor.py"], "functions": [], "depth": 10},
        )
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == _EXPECTED_RESPONSE_KEYS, (
            f"Unexpected keys: {set(body.keys()) ^ _EXPECTED_RESPONSE_KEYS}"
        )

    def test_post_blast_with_functions_returns_200(self):
        # Spec: Section 7, Criterion #12 — "functions key overrides files"
        client = _make_test_client(MULTIFILE_DIR)
        response = client.post(
            "/api/blast",
            json={
                "files": [],
                "functions": ["fixtures.processor.transform"],
                "depth": 5,
            },
        )
        assert response.status_code == 200

    def test_post_blast_input_kind_files(self):
        # Spec: Section 6 — "input_kind=files when files provided and functions empty"
        client = _make_test_client(MULTIFILE_DIR)
        response = client.post(
            "/api/blast",
            json={"files": ["processor.py"], "functions": [], "depth": 10},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["input_kind"] == "files"

    def test_post_blast_input_kind_functions(self):
        # Spec: Section 6 — "input_kind=functions when functions provided"
        client = _make_test_client(MULTIFILE_DIR)
        response = client.post(
            "/api/blast",
            json={
                "files": [],
                "functions": ["fixtures.processor.transform"],
                "depth": 5,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["input_kind"] == "functions"

    def test_post_blast_functions_wins_over_files(self):
        # Spec: Section 6 — "if both provided, functions wins"
        client = _make_test_client(MULTIFILE_DIR)
        response = client.post(
            "/api/blast",
            json={
                "files": ["processor.py"],
                "functions": ["fixtures.processor.transform"],
                "depth": 5,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["input_kind"] == "functions"

    def test_post_blast_stats_keys_present(self):
        # Spec: Section 6 — "stats has all 6 required keys"
        client = _make_test_client(MULTIFILE_DIR)
        response = client.post(
            "/api/blast",
            json={"files": ["processor.py"], "depth": 10},
        )
        assert response.status_code == 200
        stats = response.json()["stats"]
        expected_stats_keys = {
            "total_changed_functions",
            "total_downstream",
            "total_upstream",
            "total_entry_points_hit",
            "total_tests_affected",
            "max_depth",
        }
        assert expected_stats_keys.issubset(stats.keys())

    def test_post_blast_depth_default_is_10(self):
        # Spec: Section 5 — "depth defaults to 10"
        client = _make_test_client(MULTIFILE_DIR)
        response = client.post(
            "/api/blast",
            json={"files": ["processor.py"]},
        )
        assert response.status_code == 200


class TestApiBlastHttp400EmptyInput:
    # Spec: Section 7, Criterion #8 — "empty input → HTTP 400"

    def test_empty_files_and_functions_returns_400(self):
        # Spec: Section 7, Criterion #8 — "API returns HTTP 400 for empty input"
        client = _make_test_client(MULTIFILE_DIR)
        response = client.post(
            "/api/blast",
            json={"files": [], "functions": [], "depth": 10},
        )
        assert response.status_code == 400, (
            f"Expected 400, got {response.status_code}. Body:\n{response.text}"
        )

    def test_empty_input_400_detail_message(self):
        # Spec: Section 6 — '400 body has detail "Must provide at least one of: files, functions"'
        client = _make_test_client(MULTIFILE_DIR)
        response = client.post(
            "/api/blast",
            json={"files": [], "functions": []},
        )
        assert response.status_code == 400
        body = response.json()
        assert "detail" in body
        assert (
            "files" in body["detail"].lower() or "functions" in body["detail"].lower()
        )

    def test_no_payload_returns_error(self):
        # Spec: Section 7, Criterion #8 — "missing payload body is an error"
        client = _make_test_client(MULTIFILE_DIR)
        response = client.post("/api/blast", json={})
        # Empty dict → files=[], functions=[] by default → 400
        assert response.status_code == 400


class TestApiBlastHttp404UnknownQname:
    # Spec: Section 7, Criterion #9 — "unknown qname → HTTP 404"

    def test_unknown_function_returns_404(self):
        # Spec: Section 7, Criterion #9 — "API returns 404 for unknown function qname"
        client = _make_test_client(MULTIFILE_DIR)
        response = client.post(
            "/api/blast",
            json={"files": [], "functions": ["does.not.exist"], "depth": 10},
        )
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}. Body:\n{response.text}"
        )

    def test_unknown_function_404_detail_message(self):
        # Spec: Section 6 — '404 body has detail "Unknown function qname: <qname>"'
        client = _make_test_client(MULTIFILE_DIR)
        response = client.post(
            "/api/blast",
            json={"functions": ["does.not.exist"]},
        )
        assert response.status_code == 404
        body = response.json()
        assert "detail" in body
        assert "does.not.exist" in body["detail"]

    def test_unknown_function_detail_contains_qname(self):
        # Spec: Section 6 — "detail includes the unknown qname verbatim"
        qname = "totally.unknown.qname.xyz"
        client = _make_test_client(MULTIFILE_DIR)
        response = client.post(
            "/api/blast",
            json={"functions": [qname]},
        )
        assert response.status_code == 404
        body = response.json()
        assert qname in body["detail"]


class TestApiBlastDepthValidation:
    def test_depth_above_50_rejected(self):
        # Spec: Section 5 — "depth ge=1, le=50 validated by pydantic"
        client = _make_test_client(MULTIFILE_DIR)
        response = client.post(
            "/api/blast",
            json={"files": ["processor.py"], "depth": 51},
        )
        assert response.status_code == 422, (
            f"Expected 422 for depth=51, got {response.status_code}"
        )

    def test_depth_below_1_rejected(self):
        # Spec: Section 5 — "depth ge=1, le=50 validated by pydantic"
        client = _make_test_client(MULTIFILE_DIR)
        response = client.post(
            "/api/blast",
            json={"files": ["processor.py"], "depth": 0},
        )
        assert response.status_code == 422, (
            f"Expected 422 for depth=0, got {response.status_code}"
        )
