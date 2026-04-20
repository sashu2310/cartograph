"""Render a BlastRadiusReport to terminal (Rich), markdown, or JSON."""

import json

from rich.console import Console

from cartograph.blast.models import BlastInputKind, BlastRadiusReport


def render_terminal(report: BlastRadiusReport, console: Console) -> None:
    """Render to Rich console matching the terminal golden output format from spec Section 8."""
    console.print("\n[bold]CARTOGRAPH[/] blast radius\n")

    # Input section
    n = len(report.changed_functions)
    if report.input_kind == BlastInputKind.FUNCTIONS:
        noun = "function" if n == 1 else "functions"
    elif report.input_kind == BlastInputKind.FILES:
        noun = "file" if n == 1 else "files"
    else:
        noun = "function" if n == 1 else "functions"

    console.print(f"Input: {n} {noun}")
    for qname in report.changed_functions:
        console.print(f"  • {qname}")
    console.print()

    # Stats section
    s = report.stats
    console.print("[bold]Stats[/]")
    console.print(f"  Changed functions:     {s.total_changed_functions}")
    console.print(f"  Downstream:            {s.total_downstream}")
    console.print(f"  Upstream:              {s.total_upstream}")
    console.print(f"  Entry points hit:      {s.total_entry_points_hit}")
    console.print(f"  Tests affected:        {s.total_tests_affected}")
    console.print(f"  Max depth:             {s.max_depth}")
    console.print()

    # Upstream section
    upstream = [f for f in report.affected_functions if f.severity.value == "upstream"]
    if upstream:
        console.print("[bold]Upstream (what depends on this)[/]")
        for f in sorted(upstream, key=lambda x: (x.depth, x.qualified_name)):
            console.print(f"  depth {f.depth} │ {f.qualified_name}")
        console.print()

    # Downstream section
    downstream = [
        f for f in report.affected_functions if f.severity.value == "downstream"
    ]
    if downstream:
        console.print("[bold]Downstream (what this changes)[/]")
        for f in sorted(downstream, key=lambda x: (x.depth, x.qualified_name)):
            console.print(f"  depth {f.depth} │ {f.qualified_name}")
        console.print()

    # Entry points hit
    if report.affected_entry_points:
        console.print("[bold]Entry points hit[/]")
        for ep in report.affected_entry_points:
            console.print(
                f"  [{ep.entry_point_type}]  {ep.qualified_name}        {ep.trigger}"
            )
        console.print()

    # Tests affected
    if report.affected_tests:
        console.print("[bold]Tests affected[/]")
        for t in report.affected_tests:
            file_path = t.test_file
            qname_parts = t.test_qualified_name.split(".")
            # Best-effort: show as pytest node id
            console.print(f"  {file_path}::{'.'.join(qname_parts[-2:])}")
        console.print()
        console.print(
            "[dim]Tests are matched statically via imports; "
            "dynamic/fixture-driven coverage is not detected.[/]"
        )


def render_markdown(report: BlastRadiusReport) -> str:
    """Return markdown string matching the markdown golden output format from spec Section 8."""
    lines: list[str] = []
    lines.append("## Cartograph Blast Radius")
    lines.append("")

    n = len(report.changed_functions)
    if report.input_kind == BlastInputKind.FUNCTIONS:
        noun = "function" if n == 1 else "functions"
    elif report.input_kind == BlastInputKind.FILES:
        noun = "file" if n == 1 else "files"
    else:
        noun = "function" if n == 1 else "functions"

    if n == 1:
        lines.append(f"**Input:** {n} {noun} — `{report.changed_functions[0]}`")
    else:
        items = ", ".join(f"`{q}`" for q in report.changed_functions)
        lines.append(f"**Input:** {n} {noun} — {items}")
    lines.append("")

    s = report.stats
    lines.append("| Metric | Count |")
    lines.append("| --- | --- |")
    lines.append(f"| Changed functions | {s.total_changed_functions} |")
    lines.append(f"| Downstream | {s.total_downstream} |")
    lines.append(f"| Upstream | {s.total_upstream} |")
    lines.append(f"| Entry points hit | {s.total_entry_points_hit} |")
    lines.append(f"| Tests affected | {s.total_tests_affected} |")
    lines.append(f"| Max depth | {s.max_depth} |")
    lines.append("")

    lines.append("### Entry points hit")
    if report.affected_entry_points:
        for ep in report.affected_entry_points:
            lines.append(f"- `{ep.qualified_name}` — `{ep.trigger}`")
    else:
        lines.append("_None_")
    lines.append("")

    lines.append("### Tests affected")
    if report.affected_tests:
        for t in report.affected_tests:
            file_path = t.test_file
            qname_parts = t.test_qualified_name.split(".")
            pytest_id = f"{file_path}::{'.'.join(qname_parts[-2:])}"
            lines.append(f"- `{pytest_id}`")
    else:
        lines.append("_None_")
    lines.append("")

    lines.append(
        "> Tests are matched statically via imports; "
        "dynamic/fixture-driven coverage is not detected."
    )

    return "\n".join(lines)


def render_json(report: BlastRadiusReport) -> str:
    """Return JSON string matching spec Section 6 response schema."""
    d = {
        "input_kind": report.input_kind.value,
        "changed_files": report.changed_files,
        "changed_functions": report.changed_functions,
        "affected_functions": [
            {
                "qualified_name": f.qualified_name,
                "module": f.module,
                "severity": f.severity.value,
                "depth": f.depth,
                "path_from_change": f.path_from_change,
            }
            for f in report.affected_functions
        ],
        "affected_entry_points": [
            {
                "qualified_name": ep.qualified_name,
                "entry_point_type": ep.entry_point_type,
                "trigger": ep.trigger,
                "reached_via": ep.reached_via,
            }
            for ep in report.affected_entry_points
        ],
        "affected_tests": [
            {
                "test_qualified_name": t.test_qualified_name,
                "test_file": t.test_file,
                "covers": t.covers,
            }
            for t in report.affected_tests
        ],
        "stats": {
            "total_changed_functions": report.stats.total_changed_functions,
            "total_downstream": report.stats.total_downstream,
            "total_upstream": report.stats.total_upstream,
            "total_entry_points_hit": report.stats.total_entry_points_hit,
            "total_tests_affected": report.stats.total_tests_affected,
            "max_depth": report.stats.max_depth,
        },
    }
    return json.dumps(d, indent=2)
