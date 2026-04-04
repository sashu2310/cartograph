"""Tests for the call graph builder — cross-file resolution."""

from pathlib import Path

from cartograph.graph.call_graph import CallGraphBuilder
from cartograph.graph.models import ProjectIndex
from cartograph.parser.languages.python.adapter import PythonAdapter
from cartograph.parser.languages.python.frameworks.celery import CeleryDetector
from cartograph.parser.registry import FrameworkRegistry

MULTIFILE_DIR = Path(__file__).parent / "fixtures" / "multifile"


def _build_multifile_index() -> ProjectIndex:
    """Parse the multifile fixtures into a ProjectIndex."""
    adapter = PythonAdapter()
    index = ProjectIndex(root_path=str(MULTIFILE_DIR))

    for py_file in MULTIFILE_DIR.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        relative = py_file.relative_to(MULTIFILE_DIR)
        module_path = "fixtures.multifile." + str(relative.with_suffix("")).replace(
            "/", "."
        )
        module = adapter.parse_file(str(py_file), module_path)
        if module:
            # Annotate with Celery detector
            fw_registry = FrameworkRegistry()
            fw_registry.register("python", CeleryDetector())
            fw_registry.annotate_module(module, "python")
            index.modules[module.module_path] = module

    return index


class TestCallGraphBuilder:
    def setup_method(self):
        self.index = _build_multifile_index()
        builder = CallGraphBuilder(self.index)
        self.graph = builder.build()

    def test_builds_function_registry(self):
        assert len(self.graph.functions) > 0

    def test_registers_all_modules(self):
        module_names = {
            f.module_path for f in self.graph.functions.values() if f.module_path
        }
        assert "fixtures.multifile.worker" in module_names
        assert "fixtures.multifile.processor" in module_names
        assert "fixtures.multifile.notifier" in module_names
        assert "fixtures.multifile.store" in module_names

    def test_has_resolved_edges(self):
        assert self.graph.total_resolved > 0

    def test_resolves_cross_file_calls(self):
        cross_file_edges = [e for e in self.graph.edges if e.is_cross_file]
        assert len(cross_file_edges) > 0

    def test_resolves_worker_to_processor(self):
        """worker.handle_message calls processor.validate and processor.transform."""
        worker_edges = [
            e
            for e in self.graph.edges
            if "handle_message" in e.caller and "processor" in e.callee
        ]
        assert len(worker_edges) >= 1

    def test_resolves_worker_to_notifier(self):
        """worker.handle_message calls notifier.send_alert."""
        worker_notifier_edges = [
            e
            for e in self.graph.edges
            if "handle_message" in e.caller and "send_alert" in e.callee
        ]
        assert len(worker_notifier_edges) >= 1

    def test_resolves_processor_to_notifier(self):
        """processor.transform calls notifier.log_event."""
        proc_notifier_edges = [
            e
            for e in self.graph.edges
            if "transform" in e.caller and "log_event" in e.callee
        ]
        assert len(proc_notifier_edges) >= 1

    def test_resolves_same_module_calls(self):
        """processor.transform calls processor.normalize (same file)."""
        same_file_edges = [
            e
            for e in self.graph.edges
            if "transform" in e.caller
            and "normalize" in e.callee
            and not e.is_cross_file
        ]
        assert len(same_file_edges) >= 1

    def test_detects_async_boundaries(self):
        """worker.handle_message calls persist_result.delay()."""
        async_edges = [e for e in self.graph.edges if e.call.is_async_dispatch]
        assert len(async_edges) >= 1

    def test_marks_unresolved_calls(self):
        assert self.graph.total_unresolved > 0

    def test_unresolved_includes_builtins(self):
        builtin_unresolved = [u for u in self.graph.unresolved if u.reason == "builtin"]
        assert len(builtin_unresolved) >= 1

    def test_get_callees(self):
        # Find a function that has outgoing calls
        handle_msg = None
        for qname in self.graph.functions:
            if "handle_message" in qname:
                handle_msg = qname
                break
        assert handle_msg is not None
        callees = self.graph.get_callees(handle_msg)
        assert len(callees) >= 1

    def test_get_callers(self):
        # send_alert is called by handle_message (inside branch body)
        send_alert_fn = None
        for qname in self.graph.functions:
            if qname.endswith(".send_alert"):
                send_alert_fn = qname
                break
        assert send_alert_fn is not None
        callers = self.graph.get_callers(send_alert_fn)
        assert len(callers) >= 1


class TestCallGraphEdgeCases:
    def test_empty_project(self):
        index = ProjectIndex(root_path="/tmp/empty")
        builder = CallGraphBuilder(index)
        graph = builder.build()
        assert len(graph.functions) == 0
        assert len(graph.edges) == 0

    def test_single_file_project(self):
        adapter = PythonAdapter()
        single_file = Path(__file__).parent / "fixtures" / "simple_functions.py"
        module = adapter.parse_file(str(single_file), "fixtures.simple_functions")
        assert module is not None

        index = ProjectIndex(root_path=str(single_file.parent))
        index.modules[module.module_path] = module

        builder = CallGraphBuilder(index)
        graph = builder.build()

        assert len(graph.functions) > 0
        # Same-module calls should resolve
        same_module_edges = [e for e in graph.edges if not e.is_cross_file]
        assert len(same_module_edges) >= 1
