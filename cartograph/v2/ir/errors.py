"""Typed error IRs — one discriminated union per stage."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Discriminator

from cartograph.v2.ir.base import IR


class SyntaxExtractError(IR):
    kind: Literal["syntax_error"] = "syntax_error"
    path: Path
    line: int | None = None
    col: int | None = None
    detail: str


class IoExtractError(IR):
    kind: Literal["io_error"] = "io_error"
    path: Path
    detail: str


class EncodingExtractError(IR):
    kind: Literal["encoding_error"] = "encoding_error"
    path: Path
    detail: str


ExtractError = Annotated[
    SyntaxExtractError | IoExtractError | EncodingExtractError,
    Discriminator("kind"),
]


class LspCrashedError(IR):
    kind: Literal["lsp_crashed"] = "lsp_crashed"
    detail: str


class LspTimeoutError(IR):
    kind: Literal["lsp_timeout"] = "lsp_timeout"
    detail: str


class ServerUnreachableError(IR):
    kind: Literal["server_unreachable"] = "server_unreachable"
    detail: str


class ProtocolMismatchError(IR):
    kind: Literal["protocol_mismatch"] = "protocol_mismatch"
    detail: str


ResolverError = Annotated[
    LspCrashedError | LspTimeoutError | ServerUnreachableError | ProtocolMismatchError,
    Discriminator("kind"),
]


class PipelineError(IR):
    """Envelope that tags a stage error with the stage it came from."""

    stage: Literal["extract", "resolve", "annotate", "discover", "present"]
    detail: str
