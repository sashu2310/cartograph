"""Tests for mtime-based cache freshness detection."""

import os
import time
from pathlib import Path

from cartograph.cache import (
    INDEX_FILE,
    META_FILE,
    is_cache_fresh,
)
from cartograph.config import CartographConfig
from cartograph.core import parse_and_build


def _write_py(path: Path, content: str = "def hello():\n    pass\n") -> None:
    path.write_text(content, encoding="utf-8")


def _age_file(path: Path, seconds: int) -> None:
    stat = path.stat()
    os.utime(path, (stat.st_atime - seconds, stat.st_mtime - seconds))


def _age_all_sources(project: Path, seconds: int) -> None:
    for f in project.rglob("*.py"):
        _age_file(f, seconds)


class TestCacheFreshness:
    def test_no_cache_is_not_fresh(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        _write_py(project / "a.py")

        cache_dir = tmp_path / ".cartograph"
        assert is_cache_fresh(str(cache_dir), str(project)) is False

    def test_fresh_after_initial_scan(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        _write_py(project / "a.py")

        config = CartographConfig(root_path=str(project))
        _age_all_sources(project, 60)
        parse_and_build(config)

        assert (
            is_cache_fresh(
                str(project / ".cartograph"), str(project), config.exclude_dirs
            )
            is True
        )

    def test_stale_after_source_edit(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        _write_py(project / "a.py")

        config = CartographConfig(root_path=str(project))
        _age_all_sources(project, 60)
        parse_and_build(config)

        time.sleep(0.05)
        _write_py(project / "a.py", "def hello():\n    return 1\n")

        assert (
            is_cache_fresh(
                str(project / ".cartograph"), str(project), config.exclude_dirs
            )
            is False
        )

    def test_stale_when_new_file_appears(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        _write_py(project / "a.py")

        config = CartographConfig(root_path=str(project))
        _age_all_sources(project, 60)
        parse_and_build(config)

        time.sleep(0.05)
        _write_py(project / "b.py")

        assert (
            is_cache_fresh(
                str(project / ".cartograph"), str(project), config.exclude_dirs
            )
            is False
        )

    def test_excluded_dirs_do_not_invalidate(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        _write_py(project / "a.py")

        config = CartographConfig(root_path=str(project))
        _age_all_sources(project, 60)
        parse_and_build(config)

        venv = project / ".venv"
        venv.mkdir()
        time.sleep(0.05)
        _write_py(venv / "lots_of_noise.py")

        assert (
            is_cache_fresh(
                str(project / ".cartograph"), str(project), config.exclude_dirs
            )
            is True
        )

    def test_parse_and_build_reuses_fresh_cache(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        _write_py(project / "a.py")

        config = CartographConfig(root_path=str(project))
        _age_all_sources(project, 60)
        index1, _ = parse_and_build(config)

        saved_mtime = (project / ".cartograph" / INDEX_FILE).stat().st_mtime
        time.sleep(0.05)
        index2, _ = parse_and_build(config)

        assert (project / ".cartograph" / INDEX_FILE).stat().st_mtime == saved_mtime
        assert index1.root_path == index2.root_path

    def test_parse_and_build_rewrites_stale_cache(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        _write_py(project / "a.py")

        config = CartographConfig(root_path=str(project))
        _age_all_sources(project, 60)
        parse_and_build(config)

        first_mtime = (project / ".cartograph" / INDEX_FILE).stat().st_mtime

        time.sleep(0.05)
        _write_py(project / "a.py", "def hello():\n    return 2\n")
        parse_and_build(config)

        second_mtime = (project / ".cartograph" / INDEX_FILE).stat().st_mtime
        assert second_mtime > first_mtime

    def test_missing_meta_is_not_fresh(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        _write_py(project / "a.py")

        cache_dir = project / ".cartograph"
        cache_dir.mkdir()
        (cache_dir / META_FILE).write_text("{}")

        assert is_cache_fresh(str(cache_dir), str(project)) is False
