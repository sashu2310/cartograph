"""Tests for the web presenter — FastAPI endpoints + static SPA render."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from cartograph.v2.ir.analyzed import (
    AnalyzedGraph,
    ApiRouteEntry,
    DiscoveredEntry,
)
from cartograph.v2.ir.annotated import AnnotatedGraph
from cartograph.v2.ir.resolved import Edge, FunctionRef, ResolvedGraph
from cartograph.v2.stages.present.web import WebPresenter, build_app


def _fn(qname: str) -> FunctionRef:
    module, _, name = qname.rpartition(".")
    return FunctionRef(
        qname=qname,
        name=name,
        module=module,
        line_start=1,
        line_end=5,
        source_path=Path("/tmp/x.py"),
    )


def _sample_graph() -> AnalyzedGraph:
    resolved = ResolvedGraph(
        functions={
            "app.entry": _fn("app.entry"),
            "app.helper": _fn("app.helper"),
            "app.leaf": _fn("app.leaf"),
        },
        edges=(
            Edge(caller_qname="app.entry", callee_qname="app.helper", line=1),
            Edge(caller_qname="app.helper", callee_qname="app.leaf", line=2),
        ),
    )
    return AnalyzedGraph(
        annotated=AnnotatedGraph(resolved=resolved),
        entry_points=(
            DiscoveredEntry(qname="app.entry", trigger_decorator="main.command"),
            ApiRouteEntry(qname="app.helper", method="GET", path="/h"),
        ),
    )


class TestStaticRender:
    def test_render_returns_html(self):
        html = WebPresenter().render(_sample_graph(), {}).decode()
        assert "<title>" in html
        assert "cytoscape" in html.lower()


class TestApiEndpoints:
    def test_overview_returns_counts_and_kinds(self):
        client = TestClient(build_app(_sample_graph(), project_name="demo"))
        r = client.get("/api/overview")
        assert r.status_code == 200
        body = r.json()
        assert body["project_name"] == "demo"
        assert body["stats"]["total_functions"] == 3
        assert body["stats"]["total_edges"] == 2
        assert "discovered" in body["entry_points_by_type"]
        assert "api_route" in body["entry_points_by_type"]

    def test_overview_entry_shape(self):
        client = TestClient(build_app(_sample_graph()))
        body = client.get("/api/overview").json()
        eps = body["entry_points_by_type"]["api_route"]
        assert eps[0]["node_id"] == "app.helper"
        assert eps[0]["trigger"] == "GET /h"

    def test_graph_returns_subtree(self):
        client = TestClient(build_app(_sample_graph()))
        r = client.get("/api/graph/app.entry", params={"depth": 2})
        assert r.status_code == 200
        body = r.json()
        assert body["entry_point"] == "app.entry"
        assert "app.entry" in body["nodes"]
        assert "app.helper" in body["nodes"]
        assert "app.leaf" in body["nodes"]
        assert body["metadata"]["total_nodes"] == 3

    def test_graph_404_for_unknown_qname(self):
        client = TestClient(build_app(_sample_graph()))
        r = client.get("/api/graph/unknown.fn")
        assert r.status_code == 404

    def test_callers_reverse_lookup(self):
        client = TestClient(build_app(_sample_graph()))
        r = client.get("/api/callers/app.helper")
        assert r.status_code == 200
        body = r.json()
        assert body["target"] == "app.helper"
        assert len(body["callers"]) == 1
        assert body["callers"][0]["qualified_name"] == "app.entry"

    def test_search_matches_qnames(self):
        client = TestClient(build_app(_sample_graph()))
        r = client.get("/api/search", params={"q": "help"})
        assert r.status_code == 200
        body = r.json()
        assert body["query"] == "help"
        assert any(h["qualified_name"] == "app.helper" for h in body["results"])

    def test_search_respects_limit(self):
        client = TestClient(build_app(_sample_graph()))
        body = client.get("/api/search", params={"q": "app", "limit": 1}).json()
        assert len(body["results"]) == 1

    def test_search_flags_entry_points(self):
        client = TestClient(build_app(_sample_graph()))
        body = client.get("/api/search", params={"q": "entry"}).json()
        hit = next(h for h in body["results"] if h["qualified_name"] == "app.entry")
        assert hit["is_entry_point"] is True

    def test_llm_status_false_without_keys(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("CARTOGRAPH_LLM_MODEL", raising=False)
        client = TestClient(build_app(_sample_graph()))
        assert client.get("/api/llm-status").json() == {"available": False}

    def test_llm_status_true_when_key_present(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        client = TestClient(build_app(_sample_graph()))
        assert client.get("/api/llm-status").json() == {"available": True}

    def test_root_serves_html(self):
        client = TestClient(build_app(_sample_graph()))
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
        assert "<title>" in r.text
