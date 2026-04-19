"""Tests for the LLM presenter — uses pydantic-ai's TestModel (no real API)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from cartograph.v2.ir.analyzed import AnalyzedGraph, DiscoveredEntry
from cartograph.v2.ir.annotated import AnnotatedGraph
from cartograph.v2.ir.resolved import Edge, FunctionRef, ResolvedGraph
from cartograph.v2.stages.present.llm import (
    LlmPresenter,
    _serialize_flow,
    narrate_flow,
)


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


def _graph() -> AnalyzedGraph:
    resolved = ResolvedGraph(
        functions={
            "app.entry": _fn("app.entry"),
            "app.helper": _fn("app.helper"),
            "app.leaf": _fn("app.leaf"),
        },
        edges=(
            Edge(caller_qname="app.entry", callee_qname="app.helper", line=2),
            Edge(caller_qname="app.helper", callee_qname="app.leaf", line=3),
        ),
    )
    return AnalyzedGraph(
        annotated=AnnotatedGraph(resolved=resolved),
        entry_points=(
            DiscoveredEntry(qname="app.entry", trigger_decorator="main.command"),
        ),
    )


class TestFlowSerialization:
    def test_renders_root_header(self):
        text = _serialize_flow(_graph().annotated.resolved, "app.entry", depth=2)
        assert "app.entry" in text
        assert "Entry point" in text

    def test_renders_call_tree(self):
        text = _serialize_flow(_graph().annotated.resolved, "app.entry", depth=3)
        assert "app.helper" in text
        assert "app.leaf" in text

    def test_depth_limits_recursion(self):
        text = _serialize_flow(_graph().annotated.resolved, "app.entry", depth=0)
        assert "app.entry" in text
        # Depth=0 means root only, no children.
        assert "app.helper" not in text

    def test_cycle_detection_survives_self_reference(self):
        resolved = ResolvedGraph(
            functions={"a.loop": _fn("a.loop")},
            edges=(Edge(caller_qname="a.loop", callee_qname="a.loop", line=1),),
        )
        text = _serialize_flow(resolved, "a.loop", depth=5)
        assert "cycle" in text


class TestNarrateFlow:
    @pytest.mark.asyncio
    async def test_runs_against_test_model(self):
        """TestModel returns canned text without any real LLM call."""
        from pydantic_ai import Agent

        graph = _graph()
        agent = Agent(TestModel(custom_output_text="narrative here"))
        # Override the agent lookup by patching _build_agent.
        from cartograph.v2.stages.present import llm

        orig = llm._build_agent
        try:
            llm._build_agent = lambda _model: agent
            result = await narrate_flow(graph, "app.entry")
        finally:
            llm._build_agent = orig

        assert "narrative here" in result

    @pytest.mark.asyncio
    async def test_unknown_qname_raises(self):
        graph = _graph()
        with pytest.raises(ValueError, match="unknown qname"):
            await narrate_flow(graph, "nope.gone")


class TestLlmPresenter:
    def test_render_requires_entry_qname(self):
        presenter = LlmPresenter()
        with pytest.raises(ValueError, match="entry_qname"):
            presenter.render(_graph(), {})

    def test_render_invokes_narrate(self):
        """Patch narrate_flow to a stub; assert presenter calls it."""
        from cartograph.v2.stages.present import llm

        called: dict = {}

        async def fake_narrate(graph, qname, *, depth, model):
            called["qname"] = qname
            called["depth"] = depth
            called["model"] = model
            return "stub narrative"

        orig = llm.narrate_flow
        try:
            llm.narrate_flow = fake_narrate
            out = LlmPresenter().render(
                _graph(), {"entry_qname": "app.entry", "depth": 2}
            )
        finally:
            llm.narrate_flow = orig

        assert out.decode() == "stub narrative"
        assert called == {
            "qname": "app.entry",
            "depth": 2,
            "model": llm.DEFAULT_MODEL,
        }
