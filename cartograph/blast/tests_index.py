"""Static test index — maps project functions to the test cases that reference them.

Resolution is intentionally strict (exact module_path or qname match only). Fuzzy
stem-based matching produced false positives on codebases with multiple files
sharing a basename (utils.py, models.py, config.py). An unresolvable import is
skipped, not fuzzy-matched.
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path

from cartograph.graph.models import ProjectIndex


@dataclass
class TestIndex:
    __test__ = False  # prevent pytest from collecting this dataclass as a test

    # target qname -> list of test qnames that reference it
    tests_by_target: dict[str, list[str]] = field(default_factory=dict)
    # test qname -> repo-relative test file path
    test_files: dict[str, str] = field(default_factory=dict)


def build_test_index(index: ProjectIndex, test_dir: Path) -> TestIndex:
    """Walk test_dir for test_*.py files. Map each test to the project qnames it imports.

    Only exact matches are recorded:
      * ``import foo.bar`` resolves iff ``foo.bar`` is a module_path in the index.
      * ``from foo.bar import baz`` resolves iff ``foo.bar.baz`` is a known qname,
        or ``foo.bar.baz`` is a module_path (importing a submodule).
    Unresolvable imports are silently skipped.
    """
    ti = TestIndex()

    if not test_dir.exists():
        return ti

    # Exact-match lookups only
    module_to_qnames: dict[str, list[str]] = {
        mp: [f.qualified_name for f in module.functions]
        for mp, module in index.modules.items()
    }
    all_qnames: set[str] = {qn for qnames in module_to_qnames.values() for qn in qnames}

    for test_file in sorted(test_dir.rglob("test_*.py")):
        try:
            source = test_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(test_file))
        except (SyntaxError, OSError):
            continue

        try:
            rel = test_file.relative_to(test_dir.parent)
        except ValueError:
            rel = test_file
        test_module_qname = (
            str(rel.with_suffix("")).replace("/", ".").replace("\\", ".")
        )

        imported_targets: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod_name = alias.name
                    if mod_name in module_to_qnames:
                        imported_targets.update(module_to_qnames[mod_name])
            elif isinstance(node, ast.ImportFrom):
                # Skip relative imports — we don't resolve them (would need test
                # module's own path in a package) and they're rare in real test suites.
                if node.level:
                    continue
                mod = node.module or ""
                if not mod:
                    continue
                for alias in node.names:
                    full = f"{mod}.{alias.name}"
                    if full in all_qnames:
                        imported_targets.add(full)
                    elif full in module_to_qnames:
                        imported_targets.update(module_to_qnames[full])
                    elif mod in module_to_qnames:
                        # `from pkg.mod import SomeClass` — SomeClass may not be a
                        # top-level function. Attribute accesses on SomeClass will
                        # land inside pkg.mod, so record the whole module.
                        imported_targets.update(module_to_qnames[mod])

        if not imported_targets:
            continue

        test_qnames: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                parent_class = _find_parent_class(tree, node)
                if parent_class:
                    tqname = f"{test_module_qname}.{parent_class}.{node.name}"
                else:
                    tqname = f"{test_module_qname}.{node.name}"
                test_qnames.append(tqname)

        for tqname in test_qnames:
            ti.test_files[tqname] = str(test_file.relative_to(test_dir.parent))
            for target_qname in imported_targets:
                ti.tests_by_target.setdefault(target_qname, [])
                if tqname not in ti.tests_by_target[target_qname]:
                    ti.tests_by_target[target_qname].append(tqname)

    return ti


def _find_parent_class(tree: ast.Module, func_node: ast.FunctionDef) -> str | None:
    """Return the name of the enclosing TestXxx class if any, else None."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for child in ast.walk(node):
                if child is func_node:
                    return node.name
    return None
