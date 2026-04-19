"""Async JSON-RPC LSP client: id-correlated requests, notifications, timeout, semaphore-gated concurrency."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from cartograph.v2.stages.resolve.lsp.jsonrpc import (
    AsyncReader,
    ProtocolError,
    encode_message,
    notification,
    read_message,
    request,
)

DEFAULT_TIMEOUT_S = 2.0
DEFAULT_CONCURRENCY = 50


class LspError(Exception):
    """The LSP server returned an error response for a request."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"LSP error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


class LspTimeoutError(Exception):
    """A request did not receive a response within the configured timeout."""


class LspClosedError(Exception):
    """A request was made on a client that has already been closed."""


class LspClient:
    """Asyncio LSP client speaking JSON-RPC over stdin/stdout streams."""

    def __init__(
        self,
        reader: AsyncReader,
        writer: asyncio.StreamWriter,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        concurrency: int = DEFAULT_CONCURRENCY,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(concurrency)
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._write_lock = asyncio.Lock()
        self._next_id = 0
        self._reader_task: asyncio.Task[None] | None = None
        self._closed = False

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background read loop."""
        if self._reader_task is not None:
            return
        self._reader_task = asyncio.create_task(
            self._read_loop(), name="lsp-client-reader"
        )

    async def close(self) -> None:
        """Stop the read loop and fail any outstanding requests."""
        if self._closed:
            return
        self._closed = True

        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader_task

        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(LspClosedError("client closed"))
        self._pending.clear()

    # ── Outgoing messages ────────────────────────────────────────────────

    async def request(self, method: str, params: Any = None) -> Any:
        """Send a request; await the matching response (or timeout)."""
        if self._closed:
            raise LspClosedError("client closed")

        async with self._semaphore:
            request_id = self._next_id
            self._next_id += 1
            loop = asyncio.get_running_loop()
            fut: asyncio.Future[Any] = loop.create_future()
            self._pending[request_id] = fut

            await self._write(encode_message(request(method, params, request_id)))

            try:
                return await asyncio.wait_for(fut, timeout=self._timeout)
            except TimeoutError as exc:
                raise LspTimeoutError(f"{method} (id={request_id})") from exc
            finally:
                self._pending.pop(request_id, None)

    async def notify(self, method: str, params: Any = None) -> None:
        """Send a notification (fire-and-forget)."""
        if self._closed:
            raise LspClosedError("client closed")
        await self._write(encode_message(notification(method, params)))

    # ── Internals ────────────────────────────────────────────────────────

    async def _write(self, payload: bytes) -> None:
        async with self._write_lock:
            self._writer.write(payload)
            await self._writer.drain()

    async def _read_loop(self) -> None:
        """Read messages from the server, route responses to awaiters."""
        while not self._closed:
            try:
                msg = await read_message(self._reader)
            except asyncio.IncompleteReadError:
                break
            except ProtocolError:
                # Drop the connection on framing errors — fail pending futures.
                break
            except asyncio.CancelledError:
                raise
            except Exception:
                break

            msg_id = msg.get("id")
            if msg_id is None:
                # Server-originated request or notification. Not handled yet.
                continue

            fut = self._pending.pop(msg_id, None)
            if fut is None or fut.done():
                continue

            if "error" in msg:
                err = msg["error"]
                fut.set_exception(
                    LspError(
                        code=err.get("code", -1),
                        message=err.get("message", ""),
                        data=err.get("data"),
                    )
                )
            else:
                fut.set_result(msg.get("result"))

        # Read loop ending: fail any still-pending requests.
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(LspClosedError("server connection closed"))
        self._pending.clear()
