"""JSON-RPC 2.0 over Content-Length-framed HTTP-style headers, as used by LSP."""

from __future__ import annotations

import json
from typing import Any, Protocol

ENCODING = "utf-8"
CRLF = b"\r\n"


class AsyncReader(Protocol):
    """Minimal subset of asyncio.StreamReader we depend on."""

    async def readuntil(self, separator: bytes = b"\n") -> bytes: ...
    async def readexactly(self, n: int) -> bytes: ...


def encode_message(payload: dict[str, Any]) -> bytes:
    """Serialize a JSON-RPC message with its Content-Length framing."""
    body = json.dumps(payload, ensure_ascii=False).encode(ENCODING)
    header = f"Content-Length: {len(body)}\r\n\r\n".encode(ENCODING)
    return header + body


def request(method: str, params: Any, request_id: int | str) -> dict[str, Any]:
    """Build a JSON-RPC request payload (expects a response)."""
    msg: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        msg["params"] = params
    return msg


def notification(method: str, params: Any) -> dict[str, Any]:
    """Build a JSON-RPC notification payload (fire-and-forget, no id)."""
    msg: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if params is not None:
        msg["params"] = params
    return msg


class ProtocolError(Exception):
    """Raised when the stream violates JSON-RPC framing or content rules."""


async def read_message(reader: AsyncReader) -> dict[str, Any]:
    """Read one framed JSON-RPC message from an async stream.

    Raises ProtocolError on malformed framing, asyncio.IncompleteReadError if the
    stream closes mid-message.
    """
    content_length = await _read_headers(reader)
    body = await reader.readexactly(content_length)
    try:
        parsed = json.loads(body.decode(ENCODING))
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON body: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ProtocolError(f"expected JSON object, got {type(parsed).__name__}")
    return parsed


async def _read_headers(reader: AsyncReader) -> int:
    """Consume headers up to the blank line. Return Content-Length."""
    content_length: int | None = None
    while True:
        line = await reader.readuntil(CRLF)
        # Strip exactly the trailing CRLF.
        if line.endswith(CRLF):
            line = line[:-2]
        if not line:
            # Blank line — end of headers.
            break
        decoded = line.decode(ENCODING)
        if ":" not in decoded:
            raise ProtocolError(f"malformed header line: {decoded!r}")
        name, _, value = decoded.partition(":")
        if name.strip().lower() == "content-length":
            try:
                content_length = int(value.strip())
            except ValueError as exc:
                raise ProtocolError(f"invalid Content-Length value: {value!r}") from exc
    if content_length is None:
        raise ProtocolError("missing Content-Length header")
    if content_length < 0:
        raise ProtocolError(f"negative Content-Length: {content_length}")
    return content_length
