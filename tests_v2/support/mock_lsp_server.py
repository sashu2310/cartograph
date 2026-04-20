#!/usr/bin/env python3
"""Standalone mock LSP server for integration tests.

Speaks just enough LSP to exercise the client stack:
  * initialize       → returns empty capabilities
  * initialized      → notification, no-op
  * textDocument/didOpen → notification, remembers the file
  * textDocument/definition → returns a canned Location
  * shutdown / exit  → clean termination

Config via env vars (for tests to control behavior):
  MOCK_LSP_DEFINITION_URI   — URI to return as the definition target
  MOCK_LSP_DEFINITION_LINE  — line (int) in that URI
  MOCK_LSP_HOVER_MARKDOWN   — markdown value to return from hover (empty → null contents)
  MOCK_LSP_DELAY_MS         — inject latency on every request (int, ms)
  MOCK_LSP_NEVER_RESPOND    — "1" to drop responses (timeout test)
  MOCK_LSP_ERROR_ON         — method name to return an LSP error for
"""

from __future__ import annotations

import json
import os
import sys
import time

ENCODING = "utf-8"


def _read_message():
    """Read one framed LSP message from stdin (binary). Returns dict or None on EOF."""
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n", b""):
            break
        decoded = line.decode(ENCODING).rstrip("\r\n")
        if ":" in decoded:
            k, _, v = decoded.partition(":")
            headers[k.strip().lower()] = v.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode(ENCODING))


def _send(payload) -> None:
    body = json.dumps(payload).encode(ENCODING)
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode(ENCODING))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def main() -> int:
    delay_ms = int(os.environ.get("MOCK_LSP_DELAY_MS", "0"))
    never_respond = os.environ.get("MOCK_LSP_NEVER_RESPOND") == "1"
    error_on = os.environ.get("MOCK_LSP_ERROR_ON", "")
    def_uri = os.environ.get("MOCK_LSP_DEFINITION_URI", "file:///tmp/mock_target.py")
    def_line = int(os.environ.get("MOCK_LSP_DEFINITION_LINE", "0"))
    hover_markdown = os.environ.get("MOCK_LSP_HOVER_MARKDOWN", "")

    while True:
        msg = _read_message()
        if msg is None:
            return 0

        method = msg.get("method")
        msg_id = msg.get("id")

        if delay_ms:
            time.sleep(delay_ms / 1000.0)

        if method in ("initialized",):
            # Notification; no response.
            continue

        if method == "exit":
            return 0

        if never_respond:
            continue

        if method == error_on:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32603, "message": f"mock error on {method}"},
                }
            )
            continue

        if method == "initialize":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"capabilities": {}},
                }
            )
            continue

        if method == "shutdown":
            _send({"jsonrpc": "2.0", "id": msg_id, "result": None})
            continue

        if method == "textDocument/didOpen":
            continue  # notification

        if method == "textDocument/definition":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "uri": def_uri,
                        "range": {
                            "start": {"line": def_line, "character": 0},
                            "end": {"line": def_line, "character": 10},
                        },
                    },
                }
            )
            continue

        if method == "textDocument/hover":
            if hover_markdown:
                _send(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "contents": {
                                "kind": "markdown",
                                "value": hover_markdown,
                            }
                        },
                    }
                )
            else:
                _send({"jsonrpc": "2.0", "id": msg_id, "result": None})
            continue

        # Unknown request — echo a null result.
        if msg_id is not None:
            _send({"jsonrpc": "2.0", "id": msg_id, "result": None})


if __name__ == "__main__":
    sys.exit(main())
