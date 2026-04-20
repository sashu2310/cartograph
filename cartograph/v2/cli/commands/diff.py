"""carto2 diff <sha1> <sha2> — structural graph-diff between two commits."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import click
from pydantic import ValidationError

from cartograph.v2.cli._group import main
from cartograph.v2.cli._shared import _build_pipeline, parse_exclude_dirs, resolve_path
from cartograph.v2.config import DEFAULT_EXCLUDE_DIRS, RunConfig
from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.base import is_err
from cartograph.v2.stages.resolve.lsp.server import LspServer


@main.command("diff")
@click.argument("sha1", type=str)
@click.argument("sha2", type=str)
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--include-tests/--no-tests", default=False, show_default=True)
@click.option(
    "--exclude-dirs",
    default=None,
    help="Comma-separated directory names to exclude beyond defaults.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the raw GraphDiff IR as JSON to this file instead of rendering.",
)
@click.option(
    "--no-cache",
    is_flag=True,
    default=False,
    help="Force a fresh build for each SHA; ignore any cached per-commit graph.",
)
def diff_cmd(
    sha1: str,
    sha2: str,
    path: Path | None,
    include_tests: bool,
    exclude_dirs: str | None,
    output: Path | None,
    no_cache: bool,
) -> None:
    """Structural diff of the call graph between two commits.

    Accepts any ref `git rev-parse` accepts (branches, tags, short SHAs,
    `HEAD~3`). Per-SHA graphs cache under `.cartograph/v2/diff/<sha>.json`.
    """
    from cartograph.v2.analyses import diff_graphs

    extra = parse_exclude_dirs(exclude_dirs)
    project_root = resolve_path(path)
    git_root = _git_toplevel(project_root)
    subdir = project_root.resolve().relative_to(git_root)

    canonical_from = _rev_parse_commit(git_root, sha1)
    canonical_to = _rev_parse_commit(git_root, sha2)

    cache_dir = git_root / ".cartograph" / "v2" / "diff"

    click.echo(
        f"resolving {sha1} → {canonical_from[:12]}, {sha2} → {canonical_to[:12]}",
        err=True,
    )

    from_graph = _graph_for_sha(
        git_root=git_root,
        subdir=subdir,
        sha=canonical_from,
        cache_dir=cache_dir,
        include_tests=include_tests,
        extra_exclude=extra,
        use_cache=not no_cache,
    )
    to_graph = _graph_for_sha(
        git_root=git_root,
        subdir=subdir,
        sha=canonical_to,
        cache_dir=cache_dir,
        include_tests=include_tests,
        extra_exclude=extra,
        use_cache=not no_cache,
    )

    report = diff_graphs(
        from_graph,
        to_graph,
        from_sha=canonical_from,
        to_sha=canonical_to,
    )

    if output is not None:
        output.write_text(report.model_dump_json(indent=2))
        click.echo(
            f"wrote {output} "
            f"({len(report.added_edges)} edges added, "
            f"{len(report.removed_edges)} removed)",
            err=True,
        )
        return

    _pretty_diff(report)


def _git_toplevel(path: Path) -> Path:
    """Resolve the git repo containing `path`, or raise ClickException."""
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise click.ClickException("git executable not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(
            f"not a git repository: {path}\n{exc.stderr.strip()}"
        ) from exc
    return Path(out.stdout.strip())


def _rev_parse_commit(git_root: Path, ref: str) -> str:
    """Canonicalise any git ref to its 40-char commit SHA."""
    try:
        out = subprocess.run(
            ["git", "-C", str(git_root), "rev-parse", "--verify", f"{ref}^{{commit}}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(
            f"cannot resolve git ref `{ref}`: {exc.stderr.strip()}"
        ) from exc
    return out.stdout.strip()


def _graph_for_sha(
    *,
    git_root: Path,
    subdir: Path,
    sha: str,
    cache_dir: Path,
    include_tests: bool,
    extra_exclude: frozenset[str] | None,
    use_cache: bool,
) -> AnalyzedGraph:
    # `subdir` = project_root relative to git_root. We run the pipeline
    # against `worktree / subdir`, not the worktree root, so PATH into a
    # monorepo subdirectory is respected.
    cache_path = cache_dir / f"{sha}.json"
    if use_cache and cache_path.exists():
        try:
            graph = AnalyzedGraph.model_validate_json(cache_path.read_bytes())
            click.echo(f"[cache hit]  {sha[:12]}", err=True)
            return graph
        except (ValidationError, ValueError, OSError):
            # Malformed cache → treat as miss, rebuild.
            pass

    click.echo(f"[cache miss] building {sha[:12]} …", err=True)
    graph = _build_graph_at_sha(
        git_root=git_root,
        subdir=subdir,
        sha=sha,
        include_tests=include_tests,
        extra_exclude=extra_exclude,
    )
    if use_cache:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(graph.model_dump_json())
    return graph


def _build_graph_at_sha(
    *,
    git_root: Path,
    subdir: Path,
    sha: str,
    include_tests: bool,
    extra_exclude: frozenset[str] | None,
) -> AnalyzedGraph:
    tmp_parent = Path(tempfile.mkdtemp(prefix="carto2-diff-"))
    worktree_path = tmp_parent / f"wt-{sha[:12]}"
    try:
        subprocess.run(
            [
                "git",
                "-C",
                str(git_root),
                "worktree",
                "add",
                "--detach",
                "--quiet",
                str(worktree_path),
                sha,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        shutil.rmtree(tmp_parent, ignore_errors=True)
        raise click.ClickException(
            f"git worktree add failed for {sha[:12]}: {exc.stderr.strip()}"
        ) from exc

    try:
        scan_root = worktree_path / subdir
        if not scan_root.exists():
            raise click.ClickException(
                f"subdirectory {subdir} does not exist at {sha[:12]}"
            )
        exclude = DEFAULT_EXCLUDE_DIRS | (extra_exclude or frozenset())
        return asyncio.run(
            _run_pipeline(
                scan_root,
                include_tests=include_tests,
                exclude=exclude,
            )
        )
    finally:
        # rmtree runs regardless — failed `worktree remove` still frees disk.
        subprocess.run(
            [
                "git",
                "-C",
                str(git_root),
                "worktree",
                "remove",
                "--force",
                str(worktree_path),
            ],
            capture_output=True,
            text=True,
        )
        shutil.rmtree(tmp_parent, ignore_errors=True)


async def _run_pipeline(
    scan_root: Path,
    *,
    include_tests: bool,
    exclude: frozenset[str],
) -> AnalyzedGraph:
    stats: dict[str, Any] = {}
    async with LspServer(["ty", "server"]) as server:
        pipeline = _build_pipeline(server)
        result = await pipeline.build(
            RunConfig(
                project_root=scan_root,
                include_tests=include_tests,
                exclude_dirs=exclude,
            ),
            stats=stats,
        )
    if is_err(result):
        raise click.ClickException(f"pipeline failed: {result.error}")
    assert not is_err(result)
    return result.value


def _pretty_diff(report) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    console.print()
    console.print(
        f"[bold]diff[/]  [red]{report.from_sha[:12]}[/] → [green]{report.to_sha[:12]}[/]"
    )
    console.print()

    if report.is_empty:
        console.print("[dim](graphs are structurally identical)[/]")
        return

    if report.added_functions or report.removed_functions:
        t = Table(
            title=(
                f"functions ({len(report.added_functions)} added, "
                f"{len(report.removed_functions)} removed)"
            ),
            title_style="bold",
            header_style="bold",
        )
        t.add_column("Δ", style="bold")
        t.add_column("qname", style="white")
        t.add_column("kind", style="dim")
        t.add_column("location", style="dim cyan")
        for f in report.removed_functions:
            t.add_row(
                "[red]-[/]",
                f.qname,
                f.kind,
                f"{Path(f.source_path).name}:{f.line_start}",
            )
        for f in report.added_functions:
            t.add_row(
                "[green]+[/]",
                f.qname,
                f.kind,
                f"{Path(f.source_path).name}:{f.line_start}",
            )
        console.print(t)
        console.print()

    if report.added_edges or report.removed_edges:
        t = Table(
            title=(
                f"edges ({len(report.added_edges)} added, "
                f"{len(report.removed_edges)} removed)"
            ),
            title_style="bold",
            header_style="bold",
        )
        t.add_column("Δ", style="bold")
        t.add_column("caller", style="dim")
        t.add_column("→", style="dim")
        t.add_column("callee", style="white")
        t.add_column("line", justify="right", style="dim cyan")
        t.add_column("async", style="magenta")
        for e in report.removed_edges:
            t.add_row(
                "[red]-[/]",
                e.caller_qname,
                "→",
                e.callee_qname,
                str(e.line),
                e.async_kind or "",
            )
        for e in report.added_edges:
            t.add_row(
                "[green]+[/]",
                e.caller_qname,
                "→",
                e.callee_qname,
                str(e.line),
                e.async_kind or "",
            )
        console.print(t)
        console.print()

    if report.added_entries or report.removed_entries or report.entry_kind_changes:
        t = Table(
            title=(
                f"entry points ({len(report.added_entries)} added, "
                f"{len(report.removed_entries)} removed, "
                f"{len(report.entry_kind_changes)} kind-changed)"
            ),
            title_style="bold",
            header_style="bold",
        )
        t.add_column("Δ", style="bold")
        t.add_column("qname", style="white")
        t.add_column("kind", style="dim")
        for qn in report.removed_entries:
            t.add_row("[red]-[/]", qn, "")
        for qn in report.added_entries:
            t.add_row("[green]+[/]", qn, "")
        for d in report.entry_kind_changes:
            t.add_row(
                "[yellow]~[/]",
                d.qname,
                f"[red]{d.from_kind}[/] → [green]{d.to_kind}[/]",
            )
        console.print(t)
        console.print()

    if report.added_labels or report.removed_labels:
        t = Table(
            title=(
                f"labels ({len(report.added_labels)} added, "
                f"{len(report.removed_labels)} removed)"
            ),
            title_style="bold",
            header_style="bold",
        )
        t.add_column("Δ", style="bold")
        t.add_column("qname", style="white")
        t.add_column("kind", style="dim")
        t.add_column("payload", style="dim")
        for lbl in report.removed_labels:
            t.add_row("[red]-[/]", lbl.qname, lbl.label_kind, lbl.label_json)
        for lbl in report.added_labels:
            t.add_row("[green]+[/]", lbl.qname, lbl.label_kind, lbl.label_json)
        console.print(t)
        console.print()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
