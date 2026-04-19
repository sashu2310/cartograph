"""The Resolver protocol — Stage 2's contract.

A Resolver takes the full set of SyntacticModules for a project and turns them
into a ResolvedGraph. Implementations own whatever state they need (LSP
subprocesses, type-inference caches, …); the protocol's surface is pure:

    modules + project_root  →  Result[ResolvedGraph, ResolverError]

Multiple implementations exist side-by-side (TyResolver, PyreflyResolver,
JediResolver). The benchmark harness swaps them behind this protocol.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from cartograph.v2.ir.base import Err_, Ok
from cartograph.v2.ir.errors import ResolverError
from cartograph.v2.ir.resolved import ResolvedGraph
from cartograph.v2.ir.syntactic import SyntacticModule


class Resolver(Protocol):
    name: str
    version: str

    async def resolve(
        self,
        modules: tuple[SyntacticModule, ...],
        project_root: Path,
    ) -> Ok[ResolvedGraph] | Err_[ResolverError]:
        """Produce a ResolvedGraph. Idempotent wrt inputs."""
        ...
