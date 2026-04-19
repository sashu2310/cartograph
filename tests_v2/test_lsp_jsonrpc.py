"""JSON-RPC wire format."""

from __future__ import annotations

import asyncio
import io
import json

import pytest

from cartograph.v2.stages.resolve.lsp.jsonrpc import (
    ENCODING,
    ProtocolError,
    encode_message,
    notification,
    read_message,
    request,
)


class _BytesReader:
    """Minimal AsyncReader over an in-memory byte buffer."""

    def __init__(self, data: bytes) -> None:
        self._buf = io.BytesIO(data)

    async def readuntil(self, separator: bytes = b"\n") -> bytes:
        out = bytearray()
        while True:
            ch = self._buf.read(1)
            if not ch:
                raise asyncio.IncompleteReadError(bytes(out), None)
            out.extend(ch)
            if out.endswith(separator):
                return bytes(out)

    async def readexactly(self, n: int) -> bytes:
        data = self._buf.read(n)
        if len(data) != n:
            raise asyncio.IncompleteReadError(data, n)
        return data


class TestEncoding:
    def test_encode_includes_content_length(self):
        payload = {"jsonrpc": "2.0", "id": 1, "method": "test", "params": {}}
        encoded = encode_message(payload)
        body = json.dumps(payload, ensure_ascii=False).encode(ENCODING)
        assert f"Content-Length: {len(body)}".encode() in encoded
        assert encoded.endswith(body)

    def test_encode_separator_is_crlfcrlf(self):
        payload = {"jsonrpc": "2.0", "id": 1, "method": "test"}
        encoded = encode_message(payload)
        assert b"\r\n\r\n" in encoded

    def test_request_shape(self):
        msg = request("initialize", {"rootUri": "file:///x"}, 1)
        assert msg == {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"rootUri": "file:///x"},
        }

    def test_request_omits_params_when_none(self):
        msg = request("shutdown", None, 2)
        assert "params" not in msg

    def test_notification_has_no_id(self):
        msg = notification("initialized", {})
        assert "id" not in msg
        assert msg["method"] == "initialized"


class TestDecoding:
    @pytest.mark.asyncio
    async def test_reads_single_message(self):
        payload = {"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}}
        reader = _BytesReader(encode_message(payload))
        parsed = await read_message(reader)
        assert parsed == payload

    @pytest.mark.asyncio
    async def test_reads_two_messages_in_sequence(self):
        a = {"jsonrpc": "2.0", "id": 1, "result": "a"}
        b = {"jsonrpc": "2.0", "id": 2, "result": "b"}
        reader = _BytesReader(encode_message(a) + encode_message(b))
        assert await read_message(reader) == a
        assert await read_message(reader) == b

    @pytest.mark.asyncio
    async def test_missing_content_length_raises(self):
        reader = _BytesReader(b"Content-Type: application/json\r\n\r\n{}")
        with pytest.raises(ProtocolError, match="missing Content-Length"):
            await read_message(reader)

    @pytest.mark.asyncio
    async def test_invalid_content_length_raises(self):
        reader = _BytesReader(b"Content-Length: nope\r\n\r\n{}")
        with pytest.raises(ProtocolError, match="invalid Content-Length"):
            await read_message(reader)

    @pytest.mark.asyncio
    async def test_malformed_json_raises(self):
        reader = _BytesReader(b"Content-Length: 5\r\n\r\n{not-json")
        with pytest.raises(ProtocolError, match="invalid JSON body"):
            await read_message(reader)

    @pytest.mark.asyncio
    async def test_ignores_extra_headers(self):
        payload = {"jsonrpc": "2.0", "id": 1, "result": True}
        body = json.dumps(payload).encode(ENCODING)
        framed = (
            f"Content-Type: application/vscode-jsonrpc; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n\r\n"
        ).encode() + body
        reader = _BytesReader(framed)
        assert await read_message(reader) == payload
