"""Shared test fixtures for CARTOGRAPH."""

from pathlib import Path

import pytest

from cartograph.parser.languages.python.adapter import PythonAdapter

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def python_adapter():
    return PythonAdapter()


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


def parse_fixture(adapter: PythonAdapter, filename: str):
    """Helper to parse a fixture file."""
    file_path = str(FIXTURES_DIR / filename)
    module_path = f"fixtures.{filename.replace('.py', '')}"
    return adapter.parse_file(file_path, module_path)
