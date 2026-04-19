"""IR base (frozen, extra=forbid, strict) and Result[T, E] = Ok[T] | Err_[E]."""

from __future__ import annotations

from typing import Generic, Literal, TypeAlias, TypeGuard, TypeVar

from pydantic import BaseModel, ConfigDict


class IR(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        arbitrary_types_allowed=False,
    )


T = TypeVar("T")
E = TypeVar("E")


class Ok(IR, Generic[T]):
    kind: Literal["ok"] = "ok"
    value: T


class Err_(IR, Generic[E]):  # noqa: N801 — trailing underscore avoids E TypeVar collision
    kind: Literal["err"] = "err"
    error: E


Result: TypeAlias = Ok[T] | Err_[E]


def is_ok(result: Ok[T] | Err_[E]) -> TypeGuard[Ok[T]]:
    return isinstance(result, Ok)


def is_err(result: Ok[T] | Err_[E]) -> TypeGuard[Err_[E]]:
    return isinstance(result, Err_)
