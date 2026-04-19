"""carto2 benchmark — run v1 vs v2 pipelines and report structural overlap."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from cartograph.v2.cli._group import main
from cartograph.v2.cli._shared import resolve_path


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option(
    "--targets",
    default="v1,v2-ty",
    help="comma-separated producer list",
    show_default=True,
)
def benchmark(path: Path | None, targets: str) -> None:
    """Run triangulation on a project: v1 ↔ v2-ty."""
    from cartograph.v2.benchmark.metrics import compare
    from cartograph.v2.benchmark.runner import run_target

    resolved_path = resolve_path(path)

    async def _collect():
        out = {}
        for name in (t.strip() for t in targets.split(",")):
            click.echo(f"running {name} …", err=True)
            out[name] = await run_target(
                name, resolved_path, project_name=resolved_path.name
            )
        return out

    results = asyncio.run(_collect())
    names = list(results)

    click.echo("")
    click.echo(f"{'producer':<14} {'time(s)':>8} {'edges':>7} {'entries':>8}")
    click.echo("─" * 42)
    for n in names:
        r = results[n]
        click.echo(
            f"{r.target:<14} {r.wall_time_s:>8.2f} "
            f"{len(r.graph.edges):>7} {len(r.graph.entry_points):>8}"
        )

    if len(names) >= 2:
        click.echo("")
        click.echo("Pairwise overlap:")
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                r = compare(results[names[i]], results[names[j]])
                click.echo(
                    f"  {r.a.target} ↔ {r.b.target}: "
                    f"jaccard={r.jaccard:.3f}  "
                    f"shared={r.shared_edges}  "
                    f"only-{r.a.target}={r.only_a}  "
                    f"only-{r.b.target}={r.only_b}"
                )
