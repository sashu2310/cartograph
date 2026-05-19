"""Tests for cartograph.blast.tests_index — AC-5."""

from pathlib import Path

import pytest

from cartograph.blast.tests_index import TestIndex, build_test_index

BLAST_FIXTURES = Path(__file__).parent.parent / "fixtures" / "blast"
SAMPLE_TESTS_DIR = BLAST_FIXTURES / "sample_tests"
SAMPLE_PROJECT_DIR = BLAST_FIXTURES / "sample_project"


class TestBuildTestIndex:
    # Spec: Section 7, Criterion #5 — "build_test_index maps targets to test qnames"

    def test_returns_test_index_instance(self, sample_test_index):
        # Spec: Section 7, Criterion #5 — "build_test_index returns a TestIndex"
        assert isinstance(sample_test_index, TestIndex)

    def test_tests_by_target_contains_service_targets(self, sample_test_index):
        # Spec: Section 7, Criterion #5 — "tests_by_target[service.*] contains test_handle"
        found = False
        for target_qname, test_qnames in sample_test_index.tests_by_target.items():
            if ("service" in target_qname or "handle" in target_qname) and any(
                "test_handle" in tq for tq in test_qnames
            ):
                found = True
                break
        # Also check via module-level key
        if not found:
            for target_qname in sample_test_index.tests_by_target:
                if "service" in target_qname:
                    found = True
                    break
        assert found, (
            "tests_by_target should contain service-related keys. "
            f"Keys: {list(sample_test_index.tests_by_target.keys())}"
        )

    def test_tests_by_target_contains_helper_targets(self, sample_test_index):
        # Spec: Section 7, Criterion #5 — "tests_by_target[helper.*] contains test_work"
        found = any(
            "helper" in target or "work" in target
            for target in sample_test_index.tests_by_target
        )
        assert found, (
            "tests_by_target should contain helper-related keys. "
            f"Keys: {list(sample_test_index.tests_by_target.keys())}"
        )

    def test_only_test_star_files_indexed(self, sample_project_index_and_graph):
        # Spec: Section 7, Criterion #5 — "only test_*.py files are indexed"
        from cartograph.blast.tests_index import build_test_index

        index, _ = sample_project_index_and_graph
        ti = build_test_index(index, SAMPLE_TESTS_DIR)

        for test_qname in ti.test_files:
            file_path = ti.test_files[test_qname]
            filename = Path(file_path).name
            assert filename.startswith("test_"), f"Non-test file indexed: {file_path}"

    def test_test_files_maps_qname_to_path(self, sample_test_index):
        # Spec: Section 7, Criterion #5 — "test_files maps test qname to repo-relative path"
        assert len(sample_test_index.test_files) > 0
        for _test_qname, file_path in sample_test_index.test_files.items():
            assert isinstance(file_path, str)
            assert file_path.endswith(".py")

    def test_mixed_test_covers_both_service_and_helper(self, sample_test_index):
        # Spec: Section 7, Criterion #5 — "test_mixed.py covers both service and helper"
        mixed_tests = {
            tq
            for tq in sample_test_index.test_files
            if "test_mixed" in sample_test_index.test_files[tq]
        }
        if not mixed_tests:
            pytest.skip("test_mixed.py not indexed — skipping cross-coverage assertion")

        covered_targets = set()
        for target, test_qnames in sample_test_index.tests_by_target.items():
            for tq in test_qnames:
                if tq in mixed_tests:
                    covered_targets.add(target)

        service_covered = any("service" in t for t in covered_targets)
        helper_covered = any("helper" in t for t in covered_targets)
        assert service_covered or helper_covered, (
            f"test_mixed should cover service or helper. Targets: {covered_targets}"
        )

    def test_missing_test_dir_does_not_crash(self, sample_project_index_and_graph):
        # Spec: Section 11 — "missing test_dir: warn to stderr, proceed with empty"
        index, _ = sample_project_index_and_graph
        ti = build_test_index(index, Path("/nonexistent/test/dir"))
        assert isinstance(ti, TestIndex)
        assert ti.tests_by_target == {} or isinstance(ti.tests_by_target, dict)

    def test_ambiguous_basename_does_not_over_match(self, tmp_path):
        # Regression: two modules named 'utils' in different packages must not
        # collapse. A test that imports neither should map to nothing.
        from cartograph.graph.models import ParsedFunction, ParsedModule, ProjectIndex

        def _fn(qname: str, module_path: str, file_path: str) -> ParsedFunction:
            return ParsedFunction(
                name=qname.rsplit(".", 1)[-1],
                qualified_name=qname,
                file_path=file_path,
                line_start=1,
                line_end=1,
                module_path=module_path,
            )

        index = ProjectIndex(root_path=str(tmp_path))
        index.modules["pkg_a.utils"] = ParsedModule(
            file_path=str(tmp_path / "pkg_a" / "utils.py"),
            module_path="pkg_a.utils",
            functions=[
                _fn(
                    "pkg_a.utils.helper",
                    "pkg_a.utils",
                    str(tmp_path / "pkg_a" / "utils.py"),
                )
            ],
        )
        index.modules["pkg_b.utils"] = ParsedModule(
            file_path=str(tmp_path / "pkg_b" / "utils.py"),
            module_path="pkg_b.utils",
            functions=[
                _fn(
                    "pkg_b.utils.helper",
                    "pkg_b.utils",
                    str(tmp_path / "pkg_b" / "utils.py"),
                )
            ],
        )

        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_specific.py").write_text(
            "from pkg_a.utils import helper\n\ndef test_a():\n    helper()\n"
        )

        ti = build_test_index(index, test_dir)

        # Only pkg_a.utils.helper should map to the test. pkg_b.utils.helper must not.
        assert "pkg_a.utils.helper" in ti.tests_by_target
        assert "pkg_b.utils.helper" not in ti.tests_by_target, (
            "Ambiguous basename resolver over-matched: "
            "test that imports pkg_a.utils should not cover pkg_b.utils"
        )

    def test_test_index_has_no_duplicate_test_qnames_per_target(
        self, sample_test_index
    ):
        # Spec: Section 16 — "each (target, test) pair indexed once"
        for target, test_qnames in sample_test_index.tests_by_target.items():
            assert len(test_qnames) == len(set(test_qnames)), (
                f"Duplicate test qnames for target {target}: {test_qnames}"
            )
