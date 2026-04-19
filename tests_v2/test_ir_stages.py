"""Stage IRs — construction, discriminated-union routing, frozen semantics, graph indexes."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from cartograph.v2.ir.analyzed import (
    AnalyzedGraph,
    ApiRouteEntry,
    CeleryTaskEntry,
    DiscoveredEntry,
    EntryPoint,
)
from cartograph.v2.ir.annotated import (
    AnnotatedGraph,
    ApiRouteLabel,
    CeleryTaskLabel,
    SemanticLabel,
)
from cartograph.v2.ir.resolved import (
    BuiltinUnresolved,
    Edge,
    ExternalUnresolved,
    FunctionRef,
    LspUnresolved,
    ResolvedGraph,
    UnresolvedCall,
)
from cartograph.v2.ir.syntactic import (
    AsyncFunction,
    CallKind,
    CallSite,
    MethodCall,
    PlainCall,
    SyncFunction,
    SyntacticFunction,
    SyntacticModule,
)

# ──────────────────────────────────────────────────────────────────────────────
# Stage 1
# ──────────────────────────────────────────────────────────────────────────────


class TestSyntacticIR:
    def test_plain_call(self):
        call = PlainCall(name="foo", line=1, col=4)
        assert call.kind == "plain"

    def test_method_call(self):
        call = MethodCall(
            name="bar", receiver="x", receiver_chain=("x",), line=1, col=4
        )
        assert call.kind == "method"
        assert call.receiver_chain == ("x",)

    def test_call_kind_discriminator_plain(self):
        adapter = TypeAdapter(CallKind)
        parsed = adapter.validate_python(
            {"kind": "plain", "name": "foo", "line": 1, "col": 0}
        )
        assert isinstance(parsed, PlainCall)

    def test_call_kind_discriminator_method(self):
        # Use validate_json — JSON has no tuple type, so arrays coerce to tuples
        # correctly even under strict=True. This matches how cache reloads work.
        adapter = TypeAdapter(CallKind)
        parsed = adapter.validate_json(
            '{"kind": "method", "name": "bar", "receiver": "x", '
            '"receiver_chain": ["x"], "line": 1, "col": 0}'
        )
        assert isinstance(parsed, MethodCall)
        assert parsed.receiver_chain == ("x",)

    def test_call_site_with_branch_condition(self):
        site = CallSite(
            caller_qname="mod.fn",
            call=PlainCall(name="print", line=2, col=4),
            condition="x > 0",
        )
        assert site.condition == "x > 0"
        assert isinstance(site.call, PlainCall)

    def test_sync_function(self):
        from cartograph.v2.ir.syntactic import DecoratorSpec

        func = SyncFunction(
            qname="mod.fn",
            name="fn",
            line_start=1,
            line_end=5,
            decorators=(DecoratorSpec(name="cached"),),
        )
        assert func.kind == "sync"
        assert func.decorator_names == ("cached",)

    def test_async_function(self):
        func = AsyncFunction(qname="mod.fn", name="fn", line_start=1, line_end=5)
        assert func.kind == "async"

    def test_syntactic_function_discriminator(self):
        adapter = TypeAdapter(SyntacticFunction)
        parsed = adapter.validate_python(
            {
                "kind": "async",
                "qname": "m.f",
                "name": "f",
                "line_start": 1,
                "line_end": 2,
            }
        )
        assert isinstance(parsed, AsyncFunction)

    def test_module_construction(self):
        mod = SyntacticModule(
            path=Path("/tmp/foo.py"),
            module_name="foo",
            content_hash="abc123",
        )
        assert mod.language == "python"
        assert mod.functions == ()

    def test_tuples_not_lists(self):
        mod = SyntacticModule(
            path=Path("/tmp/foo.py"),
            module_name="foo",
            content_hash="a",
            functions=(SyncFunction(qname="m.f", name="f", line_start=1, line_end=2),),
        )
        assert isinstance(mod.functions, tuple)


# ──────────────────────────────────────────────────────────────────────────────
# Stage 2
# ──────────────────────────────────────────────────────────────────────────────


class TestResolvedGraph:
    def _fn(self, qname: str) -> FunctionRef:
        module, _, name = qname.rpartition(".")
        return FunctionRef(
            qname=qname,
            name=name,
            module=module,
            line_start=1,
            line_end=5,
            source_path=Path("/tmp/x.py"),
        )

    def test_indexes_built_on_construction(self):
        graph = ResolvedGraph(
            functions={
                "a.f": self._fn("a.f"),
                "a.g": self._fn("a.g"),
                "a.h": self._fn("a.h"),
            },
            edges=(
                Edge(caller_qname="a.f", callee_qname="a.g", line=1),
                Edge(caller_qname="a.f", callee_qname="a.h", line=2),
                Edge(caller_qname="a.g", callee_qname="a.h", line=3),
            ),
        )
        assert set(graph.callees_by_caller["a.f"]) == {0, 1}
        assert graph.callers_by_callee["a.h"] == (1, 2)

    def test_get_callees_o1(self):
        graph = ResolvedGraph(
            functions={"a.f": self._fn("a.f"), "a.g": self._fn("a.g")},
            edges=(Edge(caller_qname="a.f", callee_qname="a.g", line=1),),
        )
        callees = graph.get_callees("a.f")
        assert len(callees) == 1
        assert callees[0].callee_qname == "a.g"

    def test_get_callers(self):
        graph = ResolvedGraph(
            functions={"a.f": self._fn("a.f"), "a.g": self._fn("a.g")},
            edges=(Edge(caller_qname="a.f", callee_qname="a.g", line=1),),
        )
        callers = graph.get_callers("a.g")
        assert len(callers) == 1
        assert callers[0].caller_qname == "a.f"

    def test_unresolved_discriminator_builtin(self):
        adapter = TypeAdapter(UnresolvedCall)
        parsed = adapter.validate_python(
            {"reason": "builtin", "caller_qname": "m.f", "name": "print", "line": 1}
        )
        assert isinstance(parsed, BuiltinUnresolved)

    def test_unresolved_discriminator_external(self):
        adapter = TypeAdapter(UnresolvedCall)
        parsed = adapter.validate_python(
            {
                "reason": "external",
                "caller_qname": "m.f",
                "name": "get",
                "line": 1,
                "target_module": "requests",
            }
        )
        assert isinstance(parsed, ExternalUnresolved)

    def test_unresolved_discriminator_lsp(self):
        adapter = TypeAdapter(UnresolvedCall)
        parsed = adapter.validate_python(
            {
                "reason": "lsp_timeout",
                "caller_qname": "m.f",
                "name": "thing",
                "line": 1,
            }
        )
        assert isinstance(parsed, LspUnresolved)


# ──────────────────────────────────────────────────────────────────────────────
# Stage 3
# ──────────────────────────────────────────────────────────────────────────────


class TestAnnotatedGraph:
    def _empty_resolved(self) -> ResolvedGraph:
        return ResolvedGraph(functions={}, edges=())

    def test_empty(self):
        g = AnnotatedGraph(resolved=self._empty_resolved())
        assert g.labels_for("anything") == ()

    def test_label_lookup(self):
        g = AnnotatedGraph(
            resolved=self._empty_resolved(),
            labels={
                "app.views.home": (
                    ApiRouteLabel(framework="fastapi", method="GET", path="/"),
                )
            },
        )
        labels = g.labels_for("app.views.home")
        assert len(labels) == 1
        assert isinstance(labels[0], ApiRouteLabel)

    def test_semantic_label_discriminator(self):
        adapter = TypeAdapter(SemanticLabel)
        parsed = adapter.validate_python(
            {"kind": "celery_task", "framework": "celery", "queue": "default"}
        )
        assert isinstance(parsed, CeleryTaskLabel)


# ──────────────────────────────────────────────────────────────────────────────
# Stage 4
# ──────────────────────────────────────────────────────────────────────────────


class TestAnalyzedGraph:
    def _empty_annotated(self) -> AnnotatedGraph:
        return AnnotatedGraph(resolved=ResolvedGraph(functions={}, edges=()))

    def test_empty(self):
        g = AnalyzedGraph(annotated=self._empty_annotated())
        assert g.entry_points == ()

    def test_entry_point_variants(self):
        g = AnalyzedGraph(
            annotated=self._empty_annotated(),
            entry_points=(
                DiscoveredEntry(qname="cli.scan", trigger_decorator="main.command"),
                ApiRouteEntry(qname="app.home", method="GET", path="/"),
                CeleryTaskEntry(qname="tasks.send"),
            ),
        )
        assert isinstance(g.entry_points[0], DiscoveredEntry)
        assert isinstance(g.entry_points[1], ApiRouteEntry)
        assert isinstance(g.entry_points[2], CeleryTaskEntry)

    def test_entry_point_discriminator(self):
        adapter = TypeAdapter(EntryPoint)
        parsed = adapter.validate_python(
            {
                "kind": "api_route",
                "qname": "app.fn",
                "method": "POST",
                "path": "/x",
            }
        )
        assert isinstance(parsed, ApiRouteEntry)

    def test_rejects_extra_field(self):
        with pytest.raises(ValidationError):
            DiscoveredEntry(
                qname="cli.scan",
                trigger_decorator="main.command",
                sneaky="extra",  # type: ignore[call-arg]
            )
