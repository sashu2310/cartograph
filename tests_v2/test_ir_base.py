"""IR base + Result/Ok/Err_."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cartograph.v2.ir.base import IR, Err_, Ok, is_err, is_ok


class _ExampleIR(IR):
    name: str
    count: int


class TestIRBase:
    def test_construction(self):
        ir = _ExampleIR(name="foo", count=1)
        assert ir.name == "foo"
        assert ir.count == 1

    def test_frozen_rejects_mutation(self):
        ir = _ExampleIR(name="foo", count=1)
        with pytest.raises(ValidationError):
            ir.name = "bar"  # type: ignore[misc]

    def test_extra_forbid_rejects_unknown_field(self):
        with pytest.raises(ValidationError):
            _ExampleIR(name="foo", count=1, surprise="nope")  # type: ignore[call-arg]

    def test_strict_rejects_type_coercion(self):
        # strict=True — passing a str where int is declared should fail.
        with pytest.raises(ValidationError):
            _ExampleIR(name="foo", count="1")  # type: ignore[arg-type]

    def test_json_roundtrip(self):
        ir = _ExampleIR(name="foo", count=42)
        dumped = ir.model_dump_json()
        restored = _ExampleIR.model_validate_json(dumped)
        assert restored == ir


class TestResult:
    def test_ok_carries_value(self):
        result: Ok[int] = Ok(value=7)
        assert is_ok(result)
        assert not is_err(result)
        assert result.value == 7

    def test_err_carries_error(self):
        result: Err_[str] = Err_(error="oops")
        assert is_err(result)
        assert not is_ok(result)
        assert result.error == "oops"

    def test_ok_default_kind(self):
        assert Ok(value=1).kind == "ok"

    def test_err_default_kind(self):
        assert Err_(error="x").kind == "err"

    def test_ok_is_frozen(self):
        ok = Ok(value=1)
        with pytest.raises(ValidationError):
            ok.value = 2  # type: ignore[misc]
