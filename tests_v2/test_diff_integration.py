"""End-to-end for `carto2 diff`. Real pipeline, real worktrees."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from cartograph.v2.cli._group import main as carto2


@pytest.fixture
def ty_available():
    if shutil.which("ty") is None:
        pytest.skip("ty binary not on PATH")
    return True


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=test",
            "-C",
            str(cwd),
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    return root


@pytest.mark.integration
class TestDiffCliIntegration:
    def test_added_edge_surfaces_in_diff_json(self, ty_available, tmp_path):
        # Intra-module call — ty resolves local calls cleanly without a
        # pyproject; cross-module covered by the rename-impact integration.
        root = _init_repo(tmp_path)
        # Commit A: `target` and `driver` both exist; `driver` does not call `target`.
        (root / "m.py").write_text(
            "def target():\n    return 1\n\ndef driver():\n    return 42\n"
        )
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "commit A: no edge")
        sha_a = _git(root, "rev-parse", "HEAD")

        # Commit B: `driver` now calls `target` — one edge appears.
        (root / "m.py").write_text(
            "def target():\n    return 1\n\ndef driver():\n    return target()\n"
        )
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "commit B: driver calls target")
        sha_b = _git(root, "rev-parse", "HEAD")

        out_file = tmp_path / "diff.json"
        runner = CliRunner()
        result = runner.invoke(
            carto2,
            ["diff", sha_a, sha_b, str(root), "-o", str(out_file)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output

        payload = json.loads(out_file.read_text())
        assert payload["from_sha"] == sha_a
        assert payload["to_sha"] == sha_b

        added = payload["added_edges"]
        assert any(
            e["caller_qname"].endswith(".driver")
            and e["callee_qname"].endswith(".target")
            for e in added
        ), f"expected driver→target edge; got: {added}. full payload: {payload}"
        assert payload["removed_edges"] == []

    def test_cache_hit_on_second_invocation(self, ty_available, tmp_path):
        root = _init_repo(tmp_path)
        (root / "m.py").write_text("def f():\n    return 1\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "A")
        sha_a = _git(root, "rev-parse", "HEAD")

        (root / "m.py").write_text("def f():\n    return 2\n\ndef g():\n    return 3\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "B")
        sha_b = _git(root, "rev-parse", "HEAD")

        runner = CliRunner()
        out_1 = tmp_path / "d1.json"
        first = runner.invoke(
            carto2,
            ["diff", sha_a, sha_b, str(root), "-o", str(out_1)],
            catch_exceptions=False,
        )
        assert first.exit_code == 0, first.output
        cache_dir = root / ".cartograph" / "v2" / "diff"
        cached = sorted(cache_dir.glob("*.json"))
        assert len(cached) == 2
        assert {p.stem for p in cached} == {sha_a, sha_b}

        out_2 = tmp_path / "d2.json"
        second = runner.invoke(
            carto2,
            ["diff", sha_a, sha_b, str(root), "-o", str(out_2)],
            catch_exceptions=False,
        )
        assert second.exit_code == 0, second.output
        assert out_1.read_text() == out_2.read_text()
        assert "[cache hit]" in second.output

    def test_accepts_branch_names_and_canonicalises(self, ty_available, tmp_path):
        # Cache keyed by the canonical 40-char SHA, so `HEAD~1` and its
        # underlying SHA share one entry.
        root = _init_repo(tmp_path)
        (root / "m.py").write_text("def f():\n    return 1\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "A")
        sha_a = _git(root, "rev-parse", "HEAD")

        (root / "m.py").write_text(
            "def f():\n    return 1\n\ndef g():\n    return f()\n"
        )
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "B")
        sha_b = _git(root, "rev-parse", "HEAD")

        runner = CliRunner()
        out_1 = tmp_path / "d1.json"
        r1 = runner.invoke(
            carto2,
            ["diff", "HEAD~1", "HEAD", str(root), "-o", str(out_1)],
            catch_exceptions=False,
        )
        assert r1.exit_code == 0, r1.output

        d1 = json.loads(out_1.read_text())
        assert d1["from_sha"] == sha_a
        assert d1["to_sha"] == sha_b

        # Same repo, raw SHAs — should land on the same cache entries.
        out_2 = tmp_path / "d2.json"
        r2 = runner.invoke(
            carto2,
            ["diff", sha_a, sha_b, str(root), "-o", str(out_2)],
            catch_exceptions=False,
        )
        assert r2.exit_code == 0, r2.output
        assert out_1.read_text() == out_2.read_text()
        assert "[cache hit]" in r2.output

    def test_unknown_ref_raises_click_exception(self, ty_available, tmp_path):
        root = _init_repo(tmp_path)
        (root / "m.py").write_text("def f():\n    return 1\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "A")

        runner = CliRunner()
        result = runner.invoke(
            carto2,
            ["diff", "HEAD", "not-a-real-ref", str(root)],
            catch_exceptions=False,
        )
        assert result.exit_code != 0
        assert "cannot resolve git ref" in result.output

    def test_not_a_git_repo_raises_click_exception(self, ty_available, tmp_path):
        (tmp_path / "m.py").write_text("def f():\n    return 1\n")
        runner = CliRunner()
        result = runner.invoke(
            carto2,
            ["diff", "HEAD", "HEAD", str(tmp_path)],
            catch_exceptions=False,
        )
        assert result.exit_code != 0
        assert "not a git repository" in result.output
