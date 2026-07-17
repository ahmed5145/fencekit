"""Unit tests for storage-layer fencing (no Django / Redis required)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from fencekit import FencedOutError, FenceToken, fenced_update


@dataclass
class FakeRow:
    pk: int
    fence_token: int
    progress: int = 0
    status: str = "pending"


@dataclass
class FakeQuerySet:
    """Minimal Django-like QuerySet for :func:`fenced_update` unit tests."""

    rows: list[FakeRow]
    _filters: dict[str, Any] = field(default_factory=dict)

    def filter(self, *args: Any, **kwargs: Any) -> FakeQuerySet:
        if args:
            raise TypeError("positional Q objects are not supported in FakeQuerySet")
        merged = {**self._filters, **kwargs}
        return FakeQuerySet(rows=self.rows, _filters=merged)

    def update(self, **kwargs: Any) -> int:
        matched = [row for row in self.rows if self._matches(row)]
        for row in matched:
            for name, value in kwargs.items():
                setattr(row, name, value)
        return len(matched)

    def _matches(self, row: FakeRow) -> bool:
        for key, expected in self._filters.items():
            if key.endswith("__lte"):
                attr = key[: -len("__lte")]
                if getattr(row, attr) > expected:
                    return False
                continue
            if getattr(row, key) != expected:
                return False
        return True


def test_fenced_update_accepts_equal_token() -> None:
    row = FakeRow(pk=1, fence_token=3, progress=10)
    qs = FakeQuerySet([row]).filter(pk=1)
    token = FenceToken(value=3, resource="analysis:1")

    assert fenced_update(qs, token, updates={"progress": 40, "status": "running"})
    assert row.progress == 40
    assert row.status == "running"
    assert row.fence_token == 3


def test_fenced_update_accepts_newer_token_and_advances() -> None:
    row = FakeRow(pk=1, fence_token=2, progress=10)
    qs = FakeQuerySet([row]).filter(pk=1)
    token = FenceToken(value=5, resource="analysis:1")

    assert fenced_update(qs, token, updates={"progress": 90})
    assert row.progress == 90
    assert row.fence_token == 5


def test_fenced_update_rejects_stale_token() -> None:
    row = FakeRow(pk=1, fence_token=5, progress=80)
    qs = FakeQuerySet([row]).filter(pk=1)
    stale = FenceToken(value=4, resource="analysis:1")

    assert fenced_update(qs, stale, updates={"progress": 99}) is False
    assert row.progress == 80
    assert row.fence_token == 5


def test_fenced_update_raise_on_stale() -> None:
    row = FakeRow(pk=1, fence_token=5)
    qs = FakeQuerySet([row]).filter(pk=1)
    stale = FenceToken(value=1, resource="analysis:1")

    with pytest.raises(FencedOutError, match="did not update"):
        fenced_update(qs, stale, updates={"progress": 1}, raise_on_stale=True)
    assert row.progress == 0


def test_fenced_update_missing_row_returns_false() -> None:
    qs = FakeQuerySet([]).filter(pk=99)
    token = FenceToken(value=1, resource="analysis:99")
    assert fenced_update(qs, token, updates={"progress": 1}) is False


def test_fenced_update_rejects_empty_updates() -> None:
    qs = FakeQuerySet([FakeRow(pk=1, fence_token=0)]).filter(pk=1)
    token = FenceToken(value=1, resource="analysis:1")
    with pytest.raises(ValueError, match="non-empty"):
        fenced_update(qs, token, updates={})


def test_fenced_update_rejects_fence_field_in_updates() -> None:
    qs = FakeQuerySet([FakeRow(pk=1, fence_token=0)]).filter(pk=1)
    token = FenceToken(value=1, resource="analysis:1")
    with pytest.raises(ValueError, match="omit it from updates"):
        fenced_update(qs, token, updates={"fence_token": 9, "progress": 1})
