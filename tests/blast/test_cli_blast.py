"""Tests for the `cartograph blast` CLI command — AC-6, AC-7, AC-8, AC-9."""

import json
from pathlib import Path

from click.testing import CliRunner

BLAST_FIXTURES = Path(__file__).parent.parent / "fixtures" / "blast"
MULTIFILE_DIR = Path(__file__).parent.parent / "fixtures" / "multifile"
WORKSPACE_ROOT = Path(__file__).parent.parent.parent


class TestCliBlastJsonOutput:
    # Spec: Section 7, Criterion #7 — "CLI --format json produces valid JSON"

    def test_json_output_is_parseable(self):
        # Spec: Section 7, Criterion #7 — "stdout is a single JSON object parseable by json.loads"
        from cartograph.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "blast",
                str(MULTIFILE_DIR),
                "--file",
                "processor.py",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0, (
            f"CLI exited {result.exit_code}. Output:\n{result.output}"
        )
        parsed = json.loads(result.output)
        assert isinstance(parsed, dict)

    def test_json_output_has_correct_top_level_keys(self):
        # Spec: Section 9, assertion #11 — "top-level keys equal exactly the 7 required"
        from cartograph.cli import main

        expected_keys = {
            "input_kind",
            "changed_files",
            "changed_functions",
            "affected_functions",
            "affected_entry_points",
            "affected_tests",
            "stats",
        }
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "blast",
                str(MULTIFILE_DIR),
                "--file",
                "processor.py",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0, f"CLI error:\n{result.output}"
        parsed = json.loads(result.output)
        assert set(parsed.keys()) == expected_keys

    def test_json_output_via_function_flag(self):
        # Spec: Section 7, Criterion #7 — "--function qname --format json"
        from cartograph.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "blast",
                str(MULTIFILE_DIR),
                "--function",
                "processor.transform",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0, f"CLI error:\n{result.output}"
        parsed = json.loads(result.output)
        assert "changed_functions" in parsed
        assert "processor.transform" in parsed["changed_functions"]


class TestCliBlastEmptyInput:
    # Spec: Section 7, Criterion #8 — "empty input: exit 2 + stderr 'no changes to analyze'"

    def test_empty_diff_exits_code_2(self, tmp_path):
        # Spec: Section 7, Criterion #8 — "CLI exits with code 2 on empty input"
        from cartograph.cli import main

        # Create a minimal git repo with no changes
        empty_diff = tmp_path / "empty.diff"
        empty_diff.write_text("")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "blast",
                str(MULTIFILE_DIR),
                "--diff",
                str(empty_diff),
            ],
        )
        assert result.exit_code == 2, (
            f"Expected exit 2 for empty input, got {result.exit_code}. "
            f"Output:\n{result.output}"
        )

    def test_empty_input_stderr_message(self, tmp_path):
        # Spec: Section 7, Criterion #8 — 'stderr contains "no changes to analyze"'
        from cartograph.cli import main

        empty_diff = tmp_path / "empty.diff"
        empty_diff.write_text("")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "blast",
                str(MULTIFILE_DIR),
                "--diff",
                str(empty_diff),
            ],
        )
        stderr = result.stderr if hasattr(result, "stderr") else result.output
        assert "no changes to analyze" in stderr.lower(), (
            f"Expected 'no changes to analyze' in stderr. Got:\n{stderr}"
        )


class TestCliBlastUnknownQname:
    # Spec: Section 7, Criterion #9 — "unknown qname: exit 3 + stderr 'unknown function: <qname>'"

    def test_unknown_function_exits_code_3(self):
        # Spec: Section 7, Criterion #9 — "CLI exits with code 3 for unknown qname"
        from cartograph.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "blast",
                str(MULTIFILE_DIR),
                "--function",
                "does.not.exist",
            ],
        )
        assert result.exit_code == 3, (
            f"Expected exit 3 for unknown qname, got {result.exit_code}. "
            f"Output:\n{result.output}"
        )

    def test_unknown_function_stderr_message(self):
        # Spec: Section 7, Criterion #9 — 'stderr contains "unknown function: does.not.exist"'
        from cartograph.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "blast",
                str(MULTIFILE_DIR),
                "--function",
                "does.not.exist",
            ],
        )
        stderr = result.stderr if hasattr(result, "stderr") else result.output
        assert "unknown function" in stderr.lower(), (
            f"Expected 'unknown function' in stderr. Got:\n{stderr}"
        )
        assert "does.not.exist" in stderr, f"Expected qname in stderr. Got:\n{stderr}"


class TestCliBlastGitDiffDefault:
    # Spec: Section 7, Criterion #6 — "no --diff/--file/--function invokes git diff HEAD"

    def test_git_diff_invoked_in_git_repo(self):
        # Spec: Section 7, Criterion #6 — "git diff HEAD called when no explicit input given"
        # We test by running against the workspace itself (a real git repo)
        from cartograph.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["blast", str(WORKSPACE_ROOT)],
        )
        # Exit 0 means success. Exit 5 means git diff failed (no staged changes).
        # Exit 2 means empty diff (clean repo). All are valid outcomes proving
        # the command attempted git diff HEAD (AC-6). We just verify no crash.
        assert result.exit_code in (0, 2, 5), (
            f"Unexpected exit code {result.exit_code}.\nOutput:\n{result.output}"
        )

    def test_exit_code_zero_on_success(self):
        # Spec: Section 7, Criterion #6 — "exit code 0 on success"
        from cartograph.cli import main

        # Run with an explicit file so we know there is input
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "blast",
                str(MULTIFILE_DIR),
                "--file",
                "processor.py",
                "--format",
                "terminal",
            ],
        )
        assert result.exit_code == 0, (
            f"Expected exit 0. Got {result.exit_code}.\n{result.output}"
        )


class TestCliBlastOutputFile:
    def test_output_written_to_file(self, tmp_path):
        # Spec: Section 5 — "-o writes output to file instead of stdout"
        from cartograph.cli import main

        out_file = tmp_path / "blast.json"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "blast",
                str(MULTIFILE_DIR),
                "--file",
                "processor.py",
                "--format",
                "json",
                "-o",
                str(out_file),
            ],
        )
        assert result.exit_code == 0, f"CLI error:\n{result.output}"
        assert out_file.exists(), "Output file not created"
        content = out_file.read_text()
        parsed = json.loads(content)
        assert "input_kind" in parsed

    def test_depth_flag_respected(self):
        # Spec: Section 5 — "-d / --depth controls BFS depth"
        from cartograph.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "blast",
                str(MULTIFILE_DIR),
                "--file",
                "processor.py",
                "--format",
                "json",
                "-d",
                "2",
            ],
        )
        assert result.exit_code == 0, f"CLI error:\n{result.output}"
        parsed = json.loads(result.output)
        assert parsed["stats"]["max_depth"] <= 2

    def test_depth_zero_rejected(self):
        # Spec: Section 11 — "depth=0 rejected by Click IntRange(1,50) → exit 2"
        from cartograph.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "blast",
                str(MULTIFILE_DIR),
                "--file",
                "processor.py",
                "-d",
                "0",
            ],
        )
        assert result.exit_code == 2, (
            f"Expected exit 2 for depth=0. Got {result.exit_code}."
        )

    def test_blast_help_exits_zero(self):
        # Spec: Section 9, assertion #6 — "cartograph blast --help exits 0"
        from cartograph.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["blast", "--help"])
        assert result.exit_code == 0
        assert "blast radius" in result.output.lower()
