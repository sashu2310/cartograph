"""Async subprocess lifecycle for LSP servers. Spawn, access streams, terminate."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class Subprocess:
    """A running LSP server subprocess with its I/O streams."""

    proc: asyncio.subprocess.Process
    stdin: asyncio.StreamWriter
    stdout: asyncio.StreamReader
    stderr: asyncio.StreamReader

    @property
    def pid(self) -> int:
        return self.proc.pid

    @property
    def returncode(self) -> int | None:
        return self.proc.returncode

    def is_alive(self) -> bool:
        return self.proc.returncode is None


async def spawn(cmd: list[str]) -> Subprocess:
    """Spawn an LSP server subprocess with piped stdin/stdout/stderr."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if proc.stdin is None or proc.stdout is None or proc.stderr is None:
        # Should never happen when PIPE is set, but keep the type checker happy
        # and fail loudly if something's wrong.
        await _force_kill(proc)
        raise RuntimeError(f"subprocess {cmd!r} has no stdio streams")

    return Subprocess(
        proc=proc,
        stdin=proc.stdin,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


async def terminate(sp: Subprocess, timeout: float = 2.0) -> int:
    """Terminate gracefully; kill if it doesn't exit within `timeout` seconds.

    Returns the exit code.
    """
    if sp.proc.returncode is not None:
        return sp.proc.returncode

    try:
        sp.proc.terminate()
    except ProcessLookupError:
        # Already dead.
        return sp.proc.returncode or 0

    try:
        return await asyncio.wait_for(sp.proc.wait(), timeout=timeout)
    except TimeoutError:
        await _force_kill(sp.proc)
        return sp.proc.returncode or -1


async def _force_kill(proc: asyncio.subprocess.Process) -> None:
    try:
        proc.kill()
    except ProcessLookupError:
        return
    await proc.wait()
