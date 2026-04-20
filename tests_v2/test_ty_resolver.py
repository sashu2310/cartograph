"""TyResolver tests — FakeLspServer for units, real ty for one integration case."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cartograph.v2.ir.base import is_ok
from cartograph.v2.ir.resolved import (
    BuiltinUnresolved,
    ExternalUnresolved,
    LspUnresolved,
)
from cartograph.v2.stages.extract.treesitter_extractor import TreesitterExtractor
from cartograph.v2.stages.resolve.lsp.client import LspError, LspTimeoutError
from cartograph.v2.stages.resolve.lsp.server import LspServer
from cartograph.v2.stages.resolve.ty_resolver import TyResolver

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
MULTIFILE = FIXTURES / "multifile"


# ──────────────────────────────────────────────────────────────────────────────
# Fake LSP server — no subprocess, deterministic responses.
# ──────────────────────────────────────────────────────────────────────────────


class FakeLspServer:
    """Minimal subset of LspServer's interface used by TyResolver."""

    def __init__(self) -> None:
        self._opened: set[str] = set()
        self._started = False
        self._initialized = False
        # (uri, line, character) → list[Location] OR an Exception to raise.
        self.responses: dict[tuple[str, int, int], list[dict] | Exception] = {}
        self.default_response: list[dict] | Exception = []
        self.definition_log: list[tuple[str, int, int]] = []
        self.hover_responses: dict[str, str | Exception | None] = {}
        self.default_hover: str | Exception | None = None
        self.hover_log: list[tuple[str, int, int]] = []

    # ── LspServer-compatible surface ─────────────────────────────────

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def opened_uris(self) -> frozenset[str]:
        return frozenset(self._opened)

    async def start(self) -> None:
        self._started = True

    async def initialize(self, root_uri: str, initialization_options=None) -> dict:
        self._initialized = True
        return {"capabilities": {}}

    async def did_open(
        self, uri: str, text: str, *, language_id: str = "python"
    ) -> None:
        self._opened.add(uri)

    async def definition(self, uri: str, line: int, character: int) -> list[dict]:
        self.definition_log.append((uri, line, character))
        key = (uri, line, character)
        resp = self.responses.get(key, self.default_response)
        if isinstance(resp, Exception):
            raise resp
        return list(resp)

    async def hover(self, uri: str, line: int, character: int) -> str | None:
        self.hover_log.append((uri, line, character))
        resp = self.hover_responses.get(uri, self.default_hover)
        if isinstance(resp, Exception):
            raise resp
        return resp

    async def shutdown(self) -> None:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _extract_modules(*paths: Path, module_names: list[str] | None = None):
    """Extract SyntacticModules for the given files."""
    extractor = TreesitterExtractor()
    if module_names is None:
        module_names = [p.stem for p in paths]
    modules = []
    for path, name in zip(paths, module_names, strict=True):
        result = extractor.extract(path, name)
        assert is_ok(result), f"extraction failed for {path}: {result}"
        modules.append(result.value)
    return tuple(modules)


def _location(path: Path, line_0: int) -> dict:
    """Build an LSP Location targeting the given (0-based) line in `path`."""
    return {
        "uri": path.resolve().as_uri(),
        "range": {
            "start": {"line": line_0, "character": 0},
            "end": {"line": line_0, "character": 10},
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Fake-server unit tests
# ──────────────────────────────────────────────────────────────────────────────


class TestWithFakeServer:
    @pytest.mark.asyncio
    async def test_builtin_calls_short_circuit_to_builtin_unresolved(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text("def greet(n):\n    print(n)\n")
        modules = _extract_modules(src, module_names=["app"])

        fake = FakeLspServer()
        resolver = TyResolver(server=fake)  # type: ignore[arg-type]
        result = await resolver.resolve(modules, project_root=tmp_path)
        assert is_ok(result)
        graph = result.value

        # print() should never have hit the LSP — it's a known builtin.
        assert all(e.caller_qname != "app.greet" for e in graph.edges)
        builtins = [u for u in graph.unresolved if isinstance(u, BuiltinUnresolved)]
        assert any(u.name == "print" for u in builtins)
        # And the fake wasn't asked about it:
        assert not fake.definition_log

    @pytest.mark.asyncio
    async def test_resolves_plain_call_to_edge(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text(
            "def helper():\n    return 1\n\ndef driver():\n    return helper()\n"
        )
        modules = _extract_modules(src, module_names=["app"])

        fake = FakeLspServer()
        # `helper` is defined at 0-based line 0 in app.py.
        fake.default_response = [_location(src, line_0=0)]

        resolver = TyResolver(server=fake)  # type: ignore[arg-type]
        result = await resolver.resolve(modules, project_root=tmp_path)
        assert is_ok(result)
        graph = result.value

        edges = [e for e in graph.edges if e.caller_qname == "app.driver"]
        assert len(edges) == 1
        assert edges[0].callee_qname == "app.helper"

    @pytest.mark.asyncio
    async def test_empty_lsp_response_is_lsp_empty(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text("def driver():\n    mystery()\n")
        modules = _extract_modules(src, module_names=["app"])

        fake = FakeLspServer()
        fake.default_response = []

        resolver = TyResolver(server=fake)  # type: ignore[arg-type]
        result = await resolver.resolve(modules, project_root=tmp_path)
        assert is_ok(result)
        lsp_empty = [
            u
            for u in result.value.unresolved
            if isinstance(u, LspUnresolved) and u.reason == "lsp_empty"
        ]
        assert lsp_empty

    @pytest.mark.asyncio
    async def test_target_outside_project_is_external(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text("def driver():\n    external_call()\n")
        modules = _extract_modules(src, module_names=["app"])

        fake = FakeLspServer()
        # Target lives in a nonexistent module path inside a fake site-packages.
        fake.default_response = [
            {
                "uri": "file:///opt/venv/lib/python3.14/site-packages/requests/__init__.py",
                "range": {
                    "start": {"line": 42, "character": 0},
                    "end": {"line": 42, "character": 10},
                },
            }
        ]

        resolver = TyResolver(server=fake)  # type: ignore[arg-type]
        result = await resolver.resolve(modules, project_root=tmp_path)
        assert is_ok(result)
        external = [
            u for u in result.value.unresolved if isinstance(u, ExternalUnresolved)
        ]
        assert external
        assert external[0].target_module == "requests"

    @pytest.mark.asyncio
    async def test_lsp_timeout_maps_to_lsp_unresolved(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text("def driver():\n    mystery()\n")
        modules = _extract_modules(src, module_names=["app"])

        fake = FakeLspServer()
        fake.default_response = LspTimeoutError("query timed out")

        resolver = TyResolver(server=fake)  # type: ignore[arg-type]
        result = await resolver.resolve(modules, project_root=tmp_path)
        assert is_ok(result)
        lsp_errs = [
            u
            for u in result.value.unresolved
            if isinstance(u, LspUnresolved) and u.reason == "lsp_timeout"
        ]
        assert lsp_errs

    @pytest.mark.asyncio
    async def test_lsp_error_maps_to_lsp_unresolved_with_detail(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text("def driver():\n    mystery()\n")
        modules = _extract_modules(src, module_names=["app"])

        fake = FakeLspServer()
        fake.default_response = LspError(
            code=-32603, message="internal boom", data=None
        )

        resolver = TyResolver(server=fake)  # type: ignore[arg-type]
        result = await resolver.resolve(modules, project_root=tmp_path)
        assert is_ok(result)
        lsp_errs = [
            u
            for u in result.value.unresolved
            if isinstance(u, LspUnresolved) and u.reason == "lsp_error"
        ]
        assert lsp_errs
        assert lsp_errs[0].error_detail == "internal boom"

    @pytest.mark.asyncio
    async def test_method_call_positioning_targets_method_name(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text("def driver(x):\n    x.bar()\n")
        modules = _extract_modules(src, module_names=["app"])

        fake = FakeLspServer()
        resolver = TyResolver(server=fake)  # type: ignore[arg-type]
        await resolver.resolve(modules, project_root=tmp_path)

        # Exactly one definition query should have been made.
        assert len(fake.definition_log) == 1
        _, line, char = fake.definition_log[0]
        # Line is 0-based, so line 1 in 0-based = line 2 in 1-based.
        assert line == 1
        # `x.bar()` sits at col 4 (after the 4-space indent). Method name `bar`
        # starts at col 4 + len("x") + 1 = 6.
        assert char == 6

    @pytest.mark.asyncio
    async def test_functions_dict_populated(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text("def helper():\n    return 1\n")
        modules = _extract_modules(src, module_names=["app"])

        fake = FakeLspServer()
        resolver = TyResolver(server=fake)  # type: ignore[arg-type]
        result = await resolver.resolve(modules, project_root=tmp_path)
        assert is_ok(result)
        assert "app.helper" in result.value.functions
        ref = result.value.functions["app.helper"]
        assert ref.name == "helper"
        assert ref.kind == "function"

    @pytest.mark.asyncio
    async def test_classes_are_graph_nodes(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text("class Foo:\n    def bar(self):\n        return 1\n")
        modules = _extract_modules(src, module_names=["app"])

        fake = FakeLspServer()
        resolver = TyResolver(server=fake)  # type: ignore[arg-type]
        result = await resolver.resolve(modules, project_root=tmp_path)
        assert is_ok(result)
        graph = result.value

        # Class registered as a graph node with kind="class"
        assert "app.Foo" in graph.functions
        assert graph.functions["app.Foo"].kind == "class"

        # Method registered with kind="method"
        assert "app.Foo.bar" in graph.functions
        assert graph.functions["app.Foo.bar"].kind == "method"
        assert graph.functions["app.Foo.bar"].class_name == "Foo"

    @pytest.mark.asyncio
    async def test_hover_populates_edge_type_surface(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text(
            "def add(x: int, y: int) -> int:\n"
            "    return x + y\n"
            "\n"
            "def driver():\n"
            "    return add(1, 2)\n"
        )
        modules = _extract_modules(src, module_names=["app"])

        fake = FakeLspServer()
        fake.default_response = [_location(src, line_0=0)]
        fake.default_hover = (
            "```python\n"
            "def add(x: int, y: int) -> int\n"
            "```\n"
            "\n"
            "Sum of two integers."
        )

        resolver = TyResolver(server=fake)  # type: ignore[arg-type]
        result = await resolver.resolve(modules, project_root=tmp_path)
        assert is_ok(result)
        graph = result.value

        edge = next(e for e in graph.edges if e.caller_qname == "app.driver")
        assert edge.callee_qname == "app.add"
        assert edge.callee_signature == "def add(x: int, y: int) -> int"
        assert edge.callee_return_type == "int"
        assert edge.callee_hover_markdown is not None
        assert "def add" in edge.callee_hover_markdown

    @pytest.mark.asyncio
    async def test_hover_is_deduped_per_callee(self, tmp_path):
        # Guards against regression to per-edge hover (O(edges) round-trips).
        src = tmp_path / "app.py"
        src.write_text(
            "def helper():\n"
            "    return 1\n"
            "\n"
            "def driver_a():\n"
            "    return helper()\n"
            "\n"
            "def driver_b():\n"
            "    return helper()\n"
        )
        modules = _extract_modules(src, module_names=["app"])

        fake = FakeLspServer()
        fake.default_response = [_location(src, line_0=0)]
        fake.default_hover = "```python\ndef helper() -> int\n```"

        resolver = TyResolver(server=fake)  # type: ignore[arg-type]
        result = await resolver.resolve(modules, project_root=tmp_path)
        assert is_ok(result)

        assert len(fake.hover_log) == 1
        edges = [
            e for e in result.value.edges if e.callee_qname == "app.helper"
        ]
        assert len(edges) == 2
        assert all(e.callee_signature == "def helper() -> int" for e in edges)
        assert all(e.callee_return_type == "int" for e in edges)

    @pytest.mark.asyncio
    async def test_hover_timeout_leaves_edge_unpopulated(self, tmp_path):
        from cartograph.v2.stages.resolve.lsp.client import LspTimeoutError

        src = tmp_path / "app.py"
        src.write_text(
            "def helper():\n"
            "    return 1\n"
            "\n"
            "def driver():\n"
            "    return helper()\n"
        )
        modules = _extract_modules(src, module_names=["app"])

        fake = FakeLspServer()
        fake.default_response = [_location(src, line_0=0)]
        fake.default_hover = LspTimeoutError("hover timed out")

        resolver = TyResolver(server=fake)  # type: ignore[arg-type]
        result = await resolver.resolve(modules, project_root=tmp_path)
        assert is_ok(result)

        edge = next(e for e in result.value.edges if e.caller_qname == "app.driver")
        assert edge.callee_qname == "app.helper"
        assert edge.callee_signature is None
        assert edge.callee_return_type is None
        assert edge.callee_hover_markdown is None

    @pytest.mark.asyncio
    async def test_hover_empty_response_is_none(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text(
            "def helper():\n"
            "    return 1\n"
            "\n"
            "def driver():\n"
            "    return helper()\n"
        )
        modules = _extract_modules(src, module_names=["app"])

        fake = FakeLspServer()
        fake.default_response = [_location(src, line_0=0)]
        fake.default_hover = None

        resolver = TyResolver(server=fake)  # type: ignore[arg-type]
        result = await resolver.resolve(modules, project_root=tmp_path)
        assert is_ok(result)

        edge = next(e for e in result.value.edges if e.caller_qname == "app.driver")
        assert edge.callee_signature is None
        assert edge.callee_return_type is None
        assert edge.callee_hover_markdown is None

    @pytest.mark.asyncio
    async def test_constructor_call_resolves_to_class(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text(
            "class Foo:\n"
            "    def __init__(self):\n"
            "        self.x = 1\n"
            "\n"
            "def driver():\n"
            "    return Foo()\n"
        )
        modules = _extract_modules(src, module_names=["app"])

        fake = FakeLspServer()
        # ty resolves `Foo` at the call site to the class definition line.
        # class Foo sits at 0-based line 0.
        fake.default_response = [_location(src, line_0=0)]

        resolver = TyResolver(server=fake)  # type: ignore[arg-type]
        result = await resolver.resolve(modules, project_root=tmp_path)
        assert is_ok(result)
        graph = result.value

        driver_edges = [e for e in graph.edges if e.caller_qname == "app.driver"]
        callees = {e.callee_qname for e in driver_edges}
        assert "app.Foo" in callees, (
            f"expected driver → Foo edge, got callees={callees}, "
            f"unresolved={graph.unresolved}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Real-ty smoke test
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestWithRealTy:
    """Spawns an actual `ty server` against a small fixture project.

    Skipped if the `ty` binary isn't on PATH. Not a regression test for edge
    counts — just proves end-to-end that the resolver can talk to ty and
    produce SOMETHING sensible on a real codebase.
    """

    @pytest.fixture
    def ty_available(self):
        if shutil.which("ty") is None:
            pytest.skip("ty binary not on PATH")
        return True

    @pytest.mark.asyncio
    async def test_resolves_simple_intra_module_call(self, ty_available, tmp_path):
        # Minimal two-function module; edge from driver → helper.
        src = tmp_path / "app.py"
        src.write_text(
            '"""Simple intra-module call."""\n'
            "\n"
            "def helper():\n"
            "    return 42\n"
            "\n"
            "def driver():\n"
            "    return helper()\n"
        )
        modules = _extract_modules(src, module_names=["app"])

        async with LspServer(["ty", "server"]) as server:
            resolver = TyResolver(server=server)
            result = await resolver.resolve(modules, project_root=tmp_path)

        assert is_ok(result), f"resolver returned Err: {result}"
        graph = result.value
        driver_callees = graph.get_callees("app.driver")
        assert any(e.callee_qname == "app.helper" for e in driver_callees), (
            f"expected driver → helper edge; got {driver_callees}, "
            f"unresolved={graph.unresolved}"
        )

    @pytest.mark.asyncio
    async def test_hover_attaches_return_type_to_edge(self, ty_available, tmp_path):
        # Signature string is ty-version-dependent; assert on substring `int`.
        src = tmp_path / "app.py"
        src.write_text(
            '"""Typed intra-module call."""\n'
            "\n"
            "def add(x: int, y: int) -> int:\n"
            "    return x + y\n"
            "\n"
            "def driver():\n"
            "    return add(1, 2)\n"
        )
        modules = _extract_modules(src, module_names=["app"])

        async with LspServer(["ty", "server"]) as server:
            resolver = TyResolver(server=server)
            result = await resolver.resolve(modules, project_root=tmp_path)

        assert is_ok(result), f"resolver returned Err: {result}"
        graph = result.value
        driver_callees = graph.get_callees("app.driver")
        add_edges = [e for e in driver_callees if e.callee_qname == "app.add"]
        assert add_edges, (
            f"expected driver → add edge; got {driver_callees}, "
            f"unresolved={graph.unresolved}"
        )
        edge = add_edges[0]
        # Either the clean-parse field or the raw markdown must carry it.
        haystack = " ".join(
            part or "" for part in (edge.callee_return_type, edge.callee_hover_markdown)
        )
        assert "int" in haystack, (
            f"expected 'int' in callee type surface; got "
            f"signature={edge.callee_signature!r}, "
            f"return_type={edge.callee_return_type!r}, "
            f"raw={edge.callee_hover_markdown!r}"
        )
