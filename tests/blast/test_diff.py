"""Tests for cartograph.blast.diff — AC-1 and AC-2."""

from pathlib import Path

from cartograph.blast.diff import functions_in_files, parse_changed_files

MULTIFILE_DIR = Path(__file__).parent.parent / "fixtures" / "multifile"


class TestParseChangedFiles:
    # Spec: Section 7, Criterion #1 — "parse_changed_files returns Path for +++ b/foo/bar.py"

    def test_returns_added_file(self):
        # Spec: Section 7, Criterion #1 — "Added files are captured"
        diff = "--- a/foo/bar.py\n+++ b/foo/bar.py\n@@ -0,0 +1 @@\n+x = 1\n"
        result = parse_changed_files(diff, repo_root=Path("/x"))
        assert Path("foo/bar.py") in result

    def test_strips_b_prefix(self):
        # Spec: Section 7, Criterion #1 — "path is repo-relative (no b/ prefix)"
        diff = "--- /dev/null\n+++ b/foo/bar.py\n@@ -0,0 +1 @@\n+x = 1\n"
        result = parse_changed_files(diff, repo_root=Path("/x"))
        assert Path("foo/bar.py") in result
        assert all("b/" not in str(p) for p in result)

    def test_excludes_deleted_only_files(self):
        # Spec: Section 7, Criterion #1 — "deleted-only files are excluded"
        diff = "--- a/deleted.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x = 1\n"
        result = parse_changed_files(diff, repo_root=Path("/x"))
        assert Path("deleted.py") not in result

    def test_captures_modified_file(self):
        # Spec: Section 7, Criterion #1 — "modified files are captured"
        diff = "--- a/existing.py\n+++ b/existing.py\n@@ -1,2 +1,3 @@\n x = 1\n+y = 2\n"
        result = parse_changed_files(diff, repo_root=Path("/x"))
        assert Path("existing.py") in result

    def test_captures_renamed_file(self):
        # Spec: Section 7, Criterion #1 — "renamed files are captured"
        diff = "--- a/old_name.py\n+++ b/new_name.py\n@@ -1,1 +1,1 @@\n x = 1\n"
        result = parse_changed_files(diff, repo_root=Path("/x"))
        assert Path("new_name.py") in result

    def test_empty_diff_returns_empty(self):
        # Spec: Section 7, Criterion #1 — "empty diff produces no files"
        result = parse_changed_files("", repo_root=Path("/x"))
        assert result == []

    def test_no_duplicate_paths(self):
        # Spec: Section 7, Criterion #1 — "each changed file appears once"
        diff = (
            "--- a/foo.py\n+++ b/foo.py\n@@ -1,1 +1,2 @@\n x\n+y\n"
            "--- a/foo.py\n+++ b/foo.py\n@@ -2,1 +2,2 @@\n y\n+z\n"
        )
        result = parse_changed_files(diff, repo_root=Path("/x"))
        assert result.count(Path("foo.py")) == 1

    def test_sample_diff_fixture(self):
        # Spec: Section 7, Criterion #1 — "sample.diff fixture has helper.py and orphan.py"
        fixture = Path(__file__).parent.parent / "fixtures" / "blast" / "sample.diff"
        diff_text = fixture.read_text()
        result = parse_changed_files(diff_text, repo_root=Path("/repo"))
        paths = [str(p) for p in result]
        assert "helper.py" in paths
        assert "orphan.py" in paths


class TestFunctionsInFiles:
    # Spec: Section 7, Criterion #2 — "functions_in_files returns qnames for module"

    def _build_multifile_index(self):
        from cartograph.graph.models import ProjectIndex
        from cartograph.parser.languages.python.adapter import PythonAdapter

        adapter = PythonAdapter()
        index = ProjectIndex(root_path=str(MULTIFILE_DIR))
        for py_file in MULTIFILE_DIR.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
            relative = py_file.relative_to(MULTIFILE_DIR)
            module_path = "fixtures.multifile." + str(relative.with_suffix("")).replace(
                "/", "."
            )
            module = adapter.parse_file(str(py_file), module_path)
            if module:
                index.modules[module.module_path] = module
        return index

    def test_returns_all_functions_in_file(self):
        # Spec: Section 7, Criterion #2 — "returns every qname whose module is processor"
        index = self._build_multifile_index()
        result = functions_in_files(index, [Path("processor.py")])
        assert len(result) > 0
        assert all("fixtures.multifile.processor" in qname for qname in result)

    def test_returns_no_other_modules(self):
        # Spec: Section 7, Criterion #2 — "returns no qnames from other modules"
        index = self._build_multifile_index()
        result = functions_in_files(index, [Path("processor.py")])
        for qname in result:
            assert "worker" not in qname
            assert "notifier" not in qname
            assert "store" not in qname

    def test_known_functions_included(self):
        # Spec: Section 7, Criterion #2 — "validate, transform, normalize all present"
        index = self._build_multifile_index()
        result = functions_in_files(index, [Path("processor.py")])
        qname_ends = {q.split(".")[-1] for q in result}
        assert "validate" in qname_ends
        assert "transform" in qname_ends
        assert "normalize" in qname_ends

    def test_unknown_file_returns_empty(self):
        # Spec: Section 7, Criterion #2 — "unknown file produces empty list (no crash)"
        index = self._build_multifile_index()
        result = functions_in_files(index, [Path("does_not_exist.py")])
        assert result == []

    def test_multiple_files_combined(self):
        # Spec: Section 7, Criterion #2 — "multiple files produce combined qname list"
        index = self._build_multifile_index()
        result = functions_in_files(index, [Path("processor.py"), Path("notifier.py")])
        modules_hit = {q.rsplit(".", 1)[0] for q in result}
        assert any("processor" in m for m in modules_hit)
        assert any("notifier" in m for m in modules_hit)

    def test_same_basename_in_different_dirs_does_not_collapse(self, tmp_path):
        # Regression: two utils.py files in different packages must be
        # distinguished by full repo-relative path, not basename.
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

        (tmp_path / "pkg_a").mkdir()
        (tmp_path / "pkg_b").mkdir()
        a_file = tmp_path / "pkg_a" / "utils.py"
        b_file = tmp_path / "pkg_b" / "utils.py"
        a_file.write_text("def helper(): pass\n")
        b_file.write_text("def helper(): pass\n")

        index = ProjectIndex(root_path=str(tmp_path))
        index.modules["pkg_a.utils"] = ParsedModule(
            file_path=str(a_file),
            module_path="pkg_a.utils",
            functions=[_fn("pkg_a.utils.helper", "pkg_a.utils", str(a_file))],
        )
        index.modules["pkg_b.utils"] = ParsedModule(
            file_path=str(b_file),
            module_path="pkg_b.utils",
            functions=[_fn("pkg_b.utils.helper", "pkg_b.utils", str(b_file))],
        )

        # Ask for pkg_a/utils.py only
        result = functions_in_files(index, [Path("pkg_a/utils.py")])
        assert result == ["pkg_a.utils.helper"]

        # Absolute path variant should behave identically
        result_abs = functions_in_files(index, [a_file])
        assert result_abs == ["pkg_a.utils.helper"]
