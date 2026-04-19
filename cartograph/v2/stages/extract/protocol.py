"""Extractor protocol — file → SyntacticModule, pure per-file."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from cartograph.v2.ir.base import Err_, Ok
from cartograph.v2.ir.errors import ExtractError
from cartograph.v2.ir.syntactic import SyntacticModule


class Extractor(Protocol):
    language_id: str
    file_extensions: frozenset[str]

    def extract(
        self, path: Path, module_name: str
    ) -> Ok[SyntacticModule] | Err_[ExtractError]: ...
