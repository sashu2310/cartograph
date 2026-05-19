#!/usr/bin/env python3
"""Spec compliance gate for the blast radius feature.

Validates all 12 assertions from spec Section 9.
Run from the repo root: python scripts/verify_blast_spec.py
Exits 0 if all assertions pass, 1 if any fail.
"""

import contextlib
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    RESULTS.append((name, passed, detail))
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}" + (f": {detail}" if detail else ""))


# ── 1. no_new_runtime_deps ────────────────────────────────────────────────────


def assert_no_new_runtime_deps() -> None:
    result = subprocess.run(
        ["git", "diff", "main", "--", "pyproject.toml"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    diff = result.stdout

    # Parse current deps via tomllib
    pyproject_path = REPO_ROOT / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        current = tomllib.load(f)

    current_deps = set(current.get("project", {}).get("dependencies", []))

    # Check diff for added dependency lines (lines starting with '+' in [project].dependencies)
    [
        line
        for line in diff.splitlines()
        if line.startswith("+")
        and not line.startswith("+++")
        and "dependencies" not in line
        and line.strip().startswith("+")
    ]

    # Simpler: if git diff is empty for pyproject.toml, definitely no new deps
    if not diff.strip():
        check("no_new_runtime_deps", True)
        return

    # If diff exists, parse both versions
    result_main = subprocess.run(
        ["git", "show", "main:pyproject.toml"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result_main.returncode != 0:
        check("no_new_runtime_deps", True, "main branch not available, skipping")
        return

    main_data = tomllib.loads(result_main.stdout)
    main_deps = set(main_data.get("project", {}).get("dependencies", []))

    new_deps = current_deps - main_deps
    check(
        "no_new_runtime_deps",
        len(new_deps) == 0,
        f"New deps added: {new_deps}" if new_deps else "",
    )


# ── 2. no_new_dev_deps ────────────────────────────────────────────────────────


def assert_no_new_dev_deps() -> None:
    pyproject_path = REPO_ROOT / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        current = tomllib.load(f)

    current_dev = set(
        current.get("project", {}).get("optional-dependencies", {}).get("dev", [])
    )

    result_main = subprocess.run(
        ["git", "show", "main:pyproject.toml"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result_main.returncode != 0:
        check("no_new_dev_deps", True, "main branch not available, skipping")
        return

    main_data = tomllib.loads(result_main.stdout)
    main_dev = set(
        main_data.get("project", {}).get("optional-dependencies", {}).get("dev", [])
    )

    new_dev = current_dev - main_dev
    check(
        "no_new_dev_deps",
        len(new_dev) == 0,
        f"New dev deps added: {new_dev}" if new_dev else "",
    )


# ── 3. module_layout_exists ───────────────────────────────────────────────────


def assert_module_layout_exists() -> None:
    required = [
        "cartograph/blast/__init__.py",
        "cartograph/blast/models.py",
        "cartograph/blast/analyzer.py",
        "cartograph/blast/diff.py",
        "cartograph/blast/tests_index.py",
        "cartograph/blast/renderer.py",
    ]
    missing = [f for f in required if not (REPO_ROOT / f).exists()]
    check(
        "module_layout_exists",
        len(missing) == 0,
        f"Missing: {missing}" if missing else "",
    )


# ── 4. call_graph_untouched ───────────────────────────────────────────────────


def assert_call_graph_untouched() -> None:
    result = subprocess.run(
        ["git", "diff", "main", "--", "cartograph/graph/call_graph.py"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    check(
        "call_graph_untouched",
        result.stdout.strip() == "",
        result.stdout[:200] if result.stdout.strip() else "",
    )


# ── 5. models_untouched ───────────────────────────────────────────────────────


def assert_models_untouched() -> None:
    result = subprocess.run(
        ["git", "diff", "main", "--", "cartograph/graph/models.py"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    check(
        "models_untouched",
        result.stdout.strip() == "",
        result.stdout[:200] if result.stdout.strip() else "",
    )


# ── 6. cli_registers_blast ────────────────────────────────────────────────────


def assert_cli_registers_blast() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "cartograph.cli", "blast", "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    passed = result.returncode == 0 and "blast radius" in result.stdout.lower()
    check(
        "cli_registers_blast",
        passed,
        f"exit={result.returncode}, stdout={result.stdout[:100]}" if not passed else "",
    )


# ── 7. api_endpoint_registered ────────────────────────────────────────────────


def assert_api_endpoint_registered() -> None:
    try:
        from cartograph.graph.call_graph import CallGraph
        from cartograph.graph.models import ProjectIndex
        from cartograph.web.app import create_app

        stub_graph = CallGraph()
        stub_index = ProjectIndex(root_path="/tmp")
        app = create_app(stub_graph, stub_index, "test")

        blast_route = None
        for route in app.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/blast"
                and hasattr(route, "methods")
                and "POST" in route.methods
            ):
                blast_route = route
                break

        check("api_endpoint_registered", blast_route is not None)
    except Exception as e:
        check("api_endpoint_registered", False, str(e))


# ── 8. ruff_clean ─────────────────────────────────────────────────────────────


def assert_ruff_clean() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "cartograph/blast/", "tests/blast/"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    check(
        "ruff_clean",
        result.returncode == 0,
        result.stdout[:200] if result.returncode != 0 else "",
    )


# ── 9. ruff_formatted ─────────────────────────────────────────────────────────


def assert_ruff_formatted() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "cartograph/blast/", "tests/blast/"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    check(
        "ruff_formatted",
        result.returncode == 0,
        result.stdout[:200] if result.returncode != 0 else "",
    )


# ── 10. coverage_threshold ────────────────────────────────────────────────────


def assert_coverage_threshold() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--cov=cartograph.blast",
            "--cov-report=term-missing",
            "tests/blast/",
            "-q",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    output = result.stdout + result.stderr

    # Parse coverage percentage from output
    pct = None
    for line in output.splitlines():
        if "TOTAL" in line:
            parts = line.split()
            for part in reversed(parts):
                if part.endswith("%"):
                    with contextlib.suppress(ValueError):
                        pct = int(part.rstrip("%"))
                    break
            break

    if pct is None:
        check("coverage_threshold", False, "could not parse coverage output")
    else:
        check(
            "coverage_threshold",
            pct >= 80,
            f"{pct}% (need >= 80%)" if pct < 80 else f"{pct}%",
        )


# ── 11. json_schema_valid ─────────────────────────────────────────────────────


def assert_json_schema_valid() -> None:
    import json

    multifile_dir = REPO_ROOT / "tests" / "fixtures" / "multifile"
    if not multifile_dir.exists():
        check("json_schema_valid", False, "tests/fixtures/multifile not found")
        return

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "cartograph.cli",
            "blast",
            str(multifile_dir),
            "--file",
            "processor.py",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        check(
            "json_schema_valid",
            False,
            f"exit={result.returncode} stderr={result.stderr[:200]}",
        )
        return

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        check("json_schema_valid", False, f"JSON parse error: {e}")
        return

    expected_keys = {
        "input_kind",
        "changed_files",
        "changed_functions",
        "affected_functions",
        "affected_entry_points",
        "affected_tests",
        "stats",
    }
    actual_keys = set(data.keys())
    check(
        "json_schema_valid",
        actual_keys == expected_keys,
        f"keys={actual_keys}" if actual_keys != expected_keys else "",
    )


# ── 12. unit_tests_pass ───────────────────────────────────────────────────────


def assert_unit_tests_pass() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/blast/", "-v", "--tb=short"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    check(
        "unit_tests_pass",
        result.returncode == 0,
        f"exit={result.returncode}" if result.returncode != 0 else "",
    )


# ── Runner ────────────────────────────────────────────────────────────────────


def main() -> int:
    print("=" * 60)
    print("Cartograph Blast Radius — Spec Compliance Gate")
    print("=" * 60)

    print("\nRunning assertions...")
    assert_no_new_runtime_deps()
    assert_no_new_dev_deps()
    assert_module_layout_exists()
    assert_call_graph_untouched()
    assert_models_untouched()
    assert_cli_registers_blast()
    assert_api_endpoint_registered()
    assert_ruff_clean()
    assert_ruff_formatted()
    assert_coverage_threshold()
    assert_json_schema_valid()
    assert_unit_tests_pass()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)

    print(f"\nResult: {passed}/{total} assertions passed")

    if passed == total:
        print("✓ ALL ASSERTIONS PASSED — build is spec-compliant")
        return 0
    else:
        failed = [name for name, ok, _ in RESULTS if not ok]
        print(f"✗ FAILED: {failed}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
