"""Long-lived LSP server handle — one subprocess + one client, reused across resolve calls."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import logfire

from cartograph.v2.stages.resolve.lsp.client import (
    DEFAULT_CONCURRENCY,
    DEFAULT_TIMEOUT_S,
    LspClient,
    LspError,
)
from cartograph.v2.stages.resolve.lsp.subprocess import Subprocess, spawn, terminate

_SHUTDOWN_EXPECTED: tuple[type[BaseException], ...] = (
    LspError,
    ConnectionResetError,
    BrokenPipeError,
    asyncio.CancelledError,
)


class LspServer:
    """Long-lived LSP server handle. Async-context-managed."""

    def __init__(
        self,
        cmd: list[str],
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        concurrency: int = DEFAULT_CONCURRENCY,
    ) -> None:
        self._cmd = cmd
        self._timeout = timeout
        self._concurrency = concurrency
        self._subprocess: Subprocess | None = None
        self._client: LspClient | None = None
        self._initialized = False
        self._opened_uris: set[str] = set()

    # ── Context manager ─────────────────────────────────────────────────

    async def __aenter__(self) -> LspServer:
        await self.start()
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb) -> None:
        await self.shutdown()

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._subprocess is not None:
            return
        self._subprocess = await spawn(self._cmd)
        self._client = LspClient(
            self._subprocess.stdout,
            self._subprocess.stdin,
            timeout=self._timeout,
            concurrency=self._concurrency,
        )
        await self._client.start()

    async def initialize(
        self, root_uri: str, initialization_options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send `initialize` request + `initialized` notification. Idempotent."""
        client = self._require_client()
        if self._initialized:
            return {}
        params: dict[str, Any] = {
            "processId": os.getpid(),
            "rootUri": root_uri,
            "capabilities": {},
        }
        if initialization_options is not None:
            params["initializationOptions"] = initialization_options
        result = await client.request("initialize", params)
        await client.notify("initialized", {})
        self._initialized = True
        return result or {}

    async def shutdown(self) -> None:
        """Shut down cleanly: LSP shutdown + exit, then terminate process.

        Expected failures during shutdown (server dead, pipe closed, request
        cancelled) are swallowed. Anything else is logged — masking real
        errors here made LSP bugs invisible previously.
        """
        if self._client is not None:
            try:
                await self._client.request("shutdown")
            except _SHUTDOWN_EXPECTED:
                pass
            except Exception as exc:
                logfire.warn(
                    f"unexpected lsp shutdown request error: {type(exc).__name__}: {exc}"
                )
            try:
                await self._client.notify("exit")
            except _SHUTDOWN_EXPECTED:
                pass
            except Exception as exc:
                logfire.warn(
                    f"unexpected lsp exit notify error: {type(exc).__name__}: {exc}"
                )
            await self._client.close()

        if self._subprocess is not None:
            await terminate(self._subprocess)

        self._subprocess = None
        self._client = None
        self._initialized = False
        self._opened_uris.clear()

    # ── Workspace + queries ─────────────────────────────────────────────

    async def did_open(
        self, uri: str, text: str, *, language_id: str = "python"
    ) -> None:
        """Notify the server of a file it should analyze. Repeat opens are no-ops."""
        if uri in self._opened_uris:
            return
        await self._require_client().notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": language_id,
                    "version": 1,
                    "text": text,
                }
            },
        )
        self._opened_uris.add(uri)

    async def definition(
        self, uri: str, line: int, character: int
    ) -> list[dict[str, Any]]:
        """Query `textDocument/definition`. Normalizes result to a list.

        The LSP spec allows: null, a single Location, a list of Locations, or
        a list of LocationLinks. We return a list uniformly.
        """
        result = await self._require_client().request(
            "textDocument/definition",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
        )
        if result is None:
            return []
        if isinstance(result, dict):
            return [result]
        return list(result)

    async def hover(
        self, uri: str, line: int, character: int
    ) -> str | None:
        """`textDocument/hover` flattened to a single string (see LSP spec)."""
        result = await self._require_client().request(
            "textDocument/hover",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
        )
        if result is None:
            return None
        contents = result.get("contents")
        if contents is None:
            return None
        return _flatten_hover_contents(contents)

    @property
    def is_started(self) -> bool:
        return self._subprocess is not None and self._subprocess.is_alive()

    @property
    def opened_uris(self) -> frozenset[str]:
        return frozenset(self._opened_uris)

    def _require_client(self) -> LspClient:
        if self._client is None:
            raise RuntimeError("LspServer is not started; call start() first")
        return self._client


def _flatten_hover_contents(contents: Any) -> str | None:
    if isinstance(contents, str):
        return contents or None
    if isinstance(contents, dict):
        value = contents.get("value")
        return value if isinstance(value, str) and value else None
    if isinstance(contents, list):
        parts: list[str] = []
        for item in contents:
            flat = _flatten_hover_contents(item)
            if flat:
                parts.append(flat)
        return "\n".join(parts) if parts else None
    return None
