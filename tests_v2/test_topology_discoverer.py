"""TopologyDiscoverer."""

from __future__ import annotations

from pathlib import Path

from cartograph.v2.ir.analyzed import (
    ApiRouteEntry,
    CeleryTaskEntry,
    DiscoveredEntry,
)
from cartograph.v2.ir.annotated import (
    AnnotatedGraph,
    ApiRouteLabel,
    CeleryTaskLabel,
)
from cartograph.v2.ir.resolved import Edge, FunctionRef, ResolvedGraph
from cartograph.v2.stages.discover.topology import TopologyDiscoverer


def _fn(
    qname: str,
    *,
    decorators: tuple[str, ...] = (),
    path: str = "/tmp/app.py",
    kind: str = "function",
) -> FunctionRef:
    module, _, name = qname.rpartition(".")
    return FunctionRef(
        qname=qname,
        name=name,
        module=module,
        class_name=None,
        decorators=decorators,
        line_start=1,
        line_end=5,
        source_path=Path(path),
        kind=kind,  # type: ignore[arg-type]
    )


def _graph(functions: dict, edges: tuple[Edge, ...] = ()) -> ResolvedGraph:
    return ResolvedGraph(functions=functions, edges=edges)


def _annotated(resolved: ResolvedGraph, labels: dict | None = None) -> AnnotatedGraph:
    return AnnotatedGraph(resolved=resolved, labels=labels or {})


class TestBasicTopology:
    def test_function_with_decorator_zero_incoming_some_outgoing_is_entry(self):
        fns = {
            "app.root": _fn("app.root", decorators=("main.command",)),
            "app.leaf": _fn("app.leaf"),
        }
        edges = (Edge(caller_qname="app.root", callee_qname="app.leaf", line=1),)
        g = _annotated(_graph(fns, edges))

        entries = TopologyDiscoverer().discover(g)
        qnames = {e.qname for e in entries}
        assert "app.root" in qnames
        assert "app.leaf" not in qnames  # has incoming edge (from root)

    def test_function_without_decorator_is_not_entry(self):
        fns = {
            "app.thing": _fn("app.thing"),  # no decorators
            "app.helper": _fn("app.helper"),
        }
        edges = (Edge(caller_qname="app.thing", callee_qname="app.helper", line=1),)
        g = _annotated(_graph(fns, edges))

        entries = TopologyDiscoverer().discover(g)
        assert all(e.qname != "app.thing" for e in entries)

    def test_function_with_no_outgoing_is_not_entry(self):
        # Only decorator + 0 incoming, but also 0 outgoing — skip (not doing anything).
        fns = {"app.empty": _fn("app.empty", decorators=("cli.command",))}
        g = _annotated(_graph(fns))

        entries = TopologyDiscoverer().discover(g)
        assert entries == ()

    def test_function_with_incoming_edge_is_not_entry(self):
        fns = {
            "app.maybe": _fn("app.maybe", decorators=("cli.command",)),
            "app.caller": _fn("app.caller"),
            "app.leaf": _fn("app.leaf"),
        }
        edges = (
            # maybe has an incoming edge — disqualified.
            Edge(caller_qname="app.caller", callee_qname="app.maybe", line=1),
            Edge(caller_qname="app.maybe", callee_qname="app.leaf", line=2),
        )
        g = _annotated(_graph(fns, edges))

        entries = TopologyDiscoverer().discover(g)
        assert all(e.qname != "app.maybe" for e in entries)


class TestNoiseDecorators:
    def test_classmethod_only_is_not_an_entry(self):
        fns = {
            "app.method": _fn("app.method", decorators=("classmethod",)),
            "app.leaf": _fn("app.leaf"),
        }
        edges = (Edge(caller_qname="app.method", callee_qname="app.leaf", line=1),)
        g = _annotated(_graph(fns, edges))

        entries = TopologyDiscoverer().discover(g)
        assert entries == ()

    def test_pytest_fixture_is_filtered(self):
        fns = {
            "tests.setup": _fn("tests.setup", decorators=("pytest.fixture",)),
            "tests.target": _fn("tests.target"),
        }
        edges = (Edge(caller_qname="tests.setup", callee_qname="tests.target", line=1),)
        g = _annotated(_graph(fns, edges))

        entries = TopologyDiscoverer().discover(g)
        assert entries == ()

    def test_mixed_decorators_use_meaningful_one(self):
        # classmethod is noise, cli.command isn't — promote on cli.command.
        fns = {
            "app.cmd": _fn("app.cmd", decorators=("classmethod", "cli.command")),
            "app.leaf": _fn("app.leaf"),
        }
        edges = (Edge(caller_qname="app.cmd", callee_qname="app.leaf", line=1),)
        g = _annotated(_graph(fns, edges))

        entries = TopologyDiscoverer().discover(g)
        assert len(entries) == 1
        assert isinstance(entries[0], DiscoveredEntry)
        assert entries[0].trigger_decorator == "cli.command"


class TestLabelPromotion:
    def test_api_route_label_promotes_to_api_route_entry(self):
        fns = {
            "app.home": _fn("app.home", decorators=("app.get",)),
            "app.leaf": _fn("app.leaf"),
        }
        edges = (Edge(caller_qname="app.home", callee_qname="app.leaf", line=1),)
        labels = {
            "app.home": (ApiRouteLabel(framework="fastapi", method="GET", path="/"),)
        }
        g = _annotated(_graph(fns, edges), labels)

        entries = TopologyDiscoverer().discover(g)
        assert len(entries) == 1
        entry = entries[0]
        assert isinstance(entry, ApiRouteEntry)
        assert entry.method == "GET"
        assert entry.path == "/"

    def test_celery_task_label_promotes_to_celery_task_entry(self):
        fns = {
            "app.do_work": _fn("app.do_work", decorators=("celery.task",)),
            "app.leaf": _fn("app.leaf"),
        }
        edges = (Edge(caller_qname="app.do_work", callee_qname="app.leaf", line=1),)
        labels = {
            "app.do_work": (
                CeleryTaskLabel(framework="celery", queue="default", bind=False),
            )
        }
        g = _annotated(_graph(fns, edges), labels)

        entries = TopologyDiscoverer().discover(g)
        assert len(entries) == 1
        entry = entries[0]
        assert isinstance(entry, CeleryTaskEntry)
        assert entry.queue == "default"

    def test_no_label_falls_back_to_discovered_entry(self):
        fns = {
            "app.cmd": _fn("app.cmd", decorators=("main.command",)),
            "app.leaf": _fn("app.leaf"),
        }
        edges = (Edge(caller_qname="app.cmd", callee_qname="app.leaf", line=1),)
        g = _annotated(_graph(fns, edges), labels={})

        entries = TopologyDiscoverer().discover(g)
        assert len(entries) == 1
        assert isinstance(entries[0], DiscoveredEntry)
        assert entries[0].trigger_decorator == "main.command"


class TestClassSkipping:
    def test_decorated_class_with_outgoing_is_not_entry(self):
        """A @dataclass class with construction-call edges isn't an entry point."""
        fns = {
            "app.Model": _fn(
                "app.Model",
                decorators=("dataclass",),
                kind="class",
            ),
            "app.helper": _fn("app.helper"),
        }
        # Class 'uses' helper somewhere — typically a class-body default,
        # but for this unit test we simulate it with an outbound edge.
        edges = (Edge(caller_qname="app.Model", callee_qname="app.helper", line=1),)
        g = _annotated(_graph(fns, edges))

        entries = TopologyDiscoverer().discover(g)
        assert entries == (), "classes should never be entry points"

    def test_class_callees_dont_produce_entries_on_themselves(self):
        """Receiving constructor calls doesn't elevate the class — the edge
        makes it a non-root anyway, but defensive checks belt-and-suspenders."""
        fns = {
            "app.driver": _fn("app.driver", decorators=("main.command",)),
            "app.Foo": _fn("app.Foo", kind="class"),
        }
        edges = (Edge(caller_qname="app.driver", callee_qname="app.Foo", line=2),)
        g = _annotated(_graph(fns, edges))

        entries = TopologyDiscoverer().discover(g)
        # Only driver (a function with decorator, zero incoming, outgoing).
        assert len(entries) == 1
        assert entries[0].qname == "app.driver"
