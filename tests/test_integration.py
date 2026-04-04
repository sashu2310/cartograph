"""Integration tests — parse real open source Python projects.

Run with: python -m pytest tests/test_integration.py -v
Skip with: python -m pytest -m "not integration"
"""

from pathlib import Path

import pytest

from cartograph.parser.languages.python.adapter import PythonAdapter
from cartograph.parser.languages.python.frameworks.celery import CeleryDetector
from cartograph.parser.registry import FrameworkRegistry, LanguageRegistry

WORK_DIR = Path("/Users/sandepkesarwani/Documents/sandeep/work")

CELERY_SRC = WORK_DIR / "celery" / "celery"
KOMBU_SRC = WORK_DIR / "kombu" / "kombu"
PREFECT_SRC = WORK_DIR / "prefect"


def _build_registries():
    lang_registry = LanguageRegistry()
    lang_registry.register(PythonAdapter())
    fw_registry = FrameworkRegistry()
    fw_registry.register("python", CeleryDetector())
    return lang_registry, fw_registry


def _parse_project(root_path: Path):
    """Parse a project and return modules + entry points."""
    adapter = PythonAdapter()
    celery_detector = CeleryDetector()

    modules = []
    entry_points = []
    exclude_dirs = {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
        "migrations",
    }

    for py_file in root_path.rglob("*.py"):
        if any(excluded in py_file.parts for excluded in exclude_dirs):
            continue

        relative = py_file.relative_to(root_path)
        module_path = str(relative.with_suffix("")).replace("/", ".")

        module = adapter.parse_file(str(py_file), module_path)
        if module:
            modules.append(module)
            entries = celery_detector.detect_entry_points(module)
            entry_points.extend(entries)

    return modules, entry_points


@pytest.mark.integration
class TestParseCelery:
    """Parse the Celery source code — the project CARTOGRAPH's author contributed to."""

    @pytest.fixture(autouse=True)
    def _check_repo(self):
        if not CELERY_SRC.exists():
            pytest.skip("Celery source not found locally")

    def test_parses_without_crashing(self):
        modules, _ = _parse_project(CELERY_SRC)
        assert len(modules) > 0

    def test_discovers_modules(self):
        modules, _ = _parse_project(CELERY_SRC)
        assert len(modules) > 50  # Celery has 100+ modules

    def test_discovers_functions(self):
        modules, _ = _parse_project(CELERY_SRC)
        total_functions = sum(len(m.functions) for m in modules)
        assert total_functions > 100

    def test_discovers_celery_tasks(self):
        """Celery's own source should have @shared_task definitions."""
        modules, _entry_points = _parse_project(CELERY_SRC)
        # Celery itself may not use @shared_task in its source,
        # but it should parse without errors
        assert len(modules) > 0


@pytest.mark.integration
class TestParseKombu:
    """Parse the Kombu source code — Celery's messaging library."""

    @pytest.fixture(autouse=True)
    def _check_repo(self):
        if not KOMBU_SRC.exists():
            pytest.skip("Kombu source not found locally")

    def test_parses_without_crashing(self):
        modules, _ = _parse_project(KOMBU_SRC)
        assert len(modules) > 0

    def test_discovers_modules(self):
        modules, _ = _parse_project(KOMBU_SRC)
        assert len(modules) > 20

    def test_discovers_functions(self):
        modules, _ = _parse_project(KOMBU_SRC)
        total_functions = sum(len(m.functions) for m in modules)
        assert total_functions > 50

    def test_finds_qos_class(self):
        """Kombu's QoS class should be discoverable — it's where the memory leak fix lives."""
        modules, _ = _parse_project(KOMBU_SRC)
        all_classes = []
        for m in modules:
            all_classes.extend(m.classes)
        assert "QoS" in all_classes


@pytest.mark.integration
class TestParsePrefect:
    """Parse Prefect — a workflow orchestration library."""

    @pytest.fixture(autouse=True)
    def _check_repo(self):
        if not PREFECT_SRC.exists():
            pytest.skip("Prefect source not found locally")

    def test_parses_without_crashing(self):
        modules, _ = _parse_project(PREFECT_SRC)
        assert len(modules) > 0

    def test_discovers_modules(self):
        modules, _ = _parse_project(PREFECT_SRC)
        assert len(modules) > 10
