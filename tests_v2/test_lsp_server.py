"""LspServer + LspClient against the mock LSP server."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from cartograph.v2.stages.resolve.lsp.client import LspClosedError, LspTimeoutError
from cartograph.v2.stages.resolve.lsp.server import LspServer

MOCK_SCRIPT = Path(__file__).parent / "support" / "mock_lsp_server.py"


def _mock_cmd() -> list[str]:
    """Command to spawn the mock LSP server.

    Per-test env vars (MOCK_LSP_*) are set via `monkeypatch.setenv` before
    constructing the LspServer — they propagate to the child on spawn.
    """
    return [sys.executable, str(MOCK_SCRIPT)]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Clear any MOCK_LSP_* env vars left over from previous tests."""
    for key in list(os.environ):
        if key.startswith("MOCK_LSP_"):
            monkeypatch.delenv(key, raising=False)
    yield


# ──────────────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────────────


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_initialize_shutdown(self):
        server = LspServer(_mock_cmd())
        await server.start()
        try:
            result = await server.initialize(root_uri="file:///tmp/proj")
            assert result == {"capabilities": {}}
            assert server.is_started
        finally:
            await server.shutdown()
        assert not server.is_started

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        async with LspServer(_mock_cmd()) as server:
            await server.initialize(root_uri="file:///tmp/proj")
            assert server.is_started

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self):
        async with LspServer(_mock_cmd()) as server:
            await server.initialize(root_uri="file:///tmp/proj")
            # Second call is a no-op; shouldn't raise.
            await server.initialize(root_uri="file:///tmp/proj")


class TestDidOpen:
    @pytest.mark.asyncio
    async def test_did_open_tracks_uri(self):
        async with LspServer(_mock_cmd()) as server:
            await server.initialize(root_uri="file:///tmp/proj")
            await server.did_open("file:///tmp/proj/foo.py", "def foo(): pass\n")
            assert "file:///tmp/proj/foo.py" in server.opened_uris

    @pytest.mark.asyncio
    async def test_did_open_is_idempotent_per_uri(self):
        async with LspServer(_mock_cmd()) as server:
            await server.initialize(root_uri="file:///tmp/proj")
            await server.did_open("file:///tmp/proj/foo.py", "x = 1")
            await server.did_open("file:///tmp/proj/foo.py", "x = 2")
            assert len(server.opened_uris) == 1


class TestDefinition:
    @pytest.mark.asyncio
    async def test_returns_normalized_list(self, monkeypatch):
        monkeypatch.setenv("MOCK_LSP_DEFINITION_URI", "file:///tmp/target.py")
        monkeypatch.setenv("MOCK_LSP_DEFINITION_LINE", "42")
        async with LspServer(_mock_cmd()) as server:
            await server.initialize(root_uri="file:///tmp/proj")
            locations = await server.definition(
                "file:///tmp/proj/foo.py", line=3, character=4
            )
        assert len(locations) == 1
        assert locations[0]["uri"] == "file:///tmp/target.py"
        assert locations[0]["range"]["start"]["line"] == 42

    @pytest.mark.asyncio
    async def test_concurrent_requests(self):
        """50 concurrent definition queries complete correctly — validates
        request/response id correlation under load."""
        import asyncio

        async with LspServer(_mock_cmd()) as server:
            await server.initialize(root_uri="file:///tmp/proj")
            results = await asyncio.gather(
                *(
                    server.definition(f"file:///tmp/f{i}.py", line=i, character=0)
                    for i in range(50)
                )
            )
        assert len(results) == 50
        assert all(len(r) == 1 for r in results)


# ──────────────────────────────────────────────────────────────────────────────
# Error paths
# ──────────────────────────────────────────────────────────────────────────────


class TestErrors:
    @pytest.mark.asyncio
    async def test_timeout_on_unresponsive_server(self, monkeypatch):
        monkeypatch.setenv("MOCK_LSP_NEVER_RESPOND", "1")
        server = LspServer(_mock_cmd(), timeout=0.2)
        await server.start()
        try:
            with pytest.raises(LspTimeoutError):
                await server.initialize(root_uri="file:///tmp/proj")
        finally:
            await server.shutdown()

    @pytest.mark.asyncio
    async def test_lsp_error_on_method(self, monkeypatch):
        from cartograph.v2.stages.resolve.lsp.client import LspError

        monkeypatch.setenv("MOCK_LSP_ERROR_ON", "textDocument/definition")
        async with LspServer(_mock_cmd()) as server:
            await server.initialize(root_uri="file:///tmp/proj")
            with pytest.raises(LspError) as excinfo:
                await server.definition("file:///x.py", 0, 0)
            assert excinfo.value.code == -32603
            assert "mock error" in excinfo.value.message

    @pytest.mark.asyncio
    async def test_request_after_close_raises(self):
        async with LspServer(_mock_cmd()) as server:
            await server.initialize(root_uri="file:///tmp/proj")
        # Out of the `async with`; server is shut down.
        with pytest.raises((RuntimeError, LspClosedError)):
            await server.definition("file:///x.py", 0, 0)
