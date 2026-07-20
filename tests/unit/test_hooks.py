"""Unit tests for observability hooks."""

from __future__ import annotations

from datetime import timedelta

import pytest

from fencekit.errors import LockNotAcquired
from fencekit.hooks import FenceKitHooks, key_label
from fencekit.idempotency import IdempotencyGuard
from fencekit.lock import DistributedLock
from fencekit.types import BeginOutcome


class _FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool:
        del ex
        if nx and key in self._data:
            return False
        self._data[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._data:
                del self._data[key]
                count += 1
        return count

    def eval(self, *args: object, **kwargs: object) -> int:
        del args, kwargs
        return 1


def test_key_label_truncates_long_keys() -> None:
    assert key_label("abcdefghijklmnop") == "...klmnop"


def test_hooks_idempotency_begin_fires() -> None:
    events: list[tuple[str, bool]] = []
    hooks = FenceKitHooks(on_idempotency_begin=events.append)
    guard = IdempotencyGuard(_FakeRedis(), prefix="t", hooks=hooks)

    assert guard.try_begin("job-1", ttl=timedelta(seconds=30)) is True
    assert events == [("job-1", True)]


def test_hooks_swallow_callback_errors() -> None:
    def boom(_key: str, _won: bool) -> None:
        raise RuntimeError("metrics down")

    hooks = FenceKitHooks(on_idempotency_begin=boom)
    guard = IdempotencyGuard(_FakeRedis(), prefix="t", hooks=hooks)
    assert guard.try_begin("job-2", ttl=timedelta(seconds=30)) is True


def test_hooks_lock_acquire_failed() -> None:
    failed: list[str] = []

    class _ContendedRedis:
        def eval(self, *args: object, **kwargs: object) -> bool:
            del args, kwargs
            return False

    hooks = FenceKitHooks(on_lock_acquire_failed=failed.append)
    lock = DistributedLock(_ContendedRedis(), prefix="t", hooks=hooks)

    with pytest.raises(LockNotAcquired):
        lock.acquire("busy", ttl=timedelta(seconds=1))

    assert failed == ["busy"]


def test_hooks_idempotency_outcome_on_reclaim_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes: list[tuple[str, BeginOutcome]] = []
    hooks = FenceKitHooks(on_idempotency_outcome=outcomes.append)
    guard = IdempotencyGuard(_FakeRedis(), prefix="t", hooks=hooks)
    lock = DistributedLock(_FakeRedis(), prefix="t")

    monkeypatch.setattr(guard, "status", lambda _key: "pending")
    monkeypatch.setattr(guard, "try_begin", lambda *_a, **_k: False)
    monkeypatch.setattr(
        guard._client,
        "eval",
        lambda *_a, **_k: 1,
    )

    result = guard.try_begin_or_reclaim(
        "job-3",
        lock=lock,
        lock_resource="res",
        ttl=timedelta(seconds=30),
    )
    assert result == BeginOutcome.RECLAIMED
    assert outcomes == [("job-3", BeginOutcome.RECLAIMED)]
