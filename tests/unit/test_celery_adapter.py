"""Unit tests for the optional Celery decorator."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("celery")

from fencekit.celery import idempotent_task
from fencekit.idempotency import IdempotencyGuard
from fencekit.lock import DistributedLock
from fencekit.types import BeginOutcome


class _FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
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

    def eval(self, script: str, numkeys: int, *args: Any) -> Any:
        raise NotImplementedError("use guard.try_begin_or_reclaim mock in these tests")


def test_idempotent_task_runs_and_marks_done(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    guard = IdempotencyGuard(redis, prefix="t")
    lock = DistributedLock(redis, prefix="t")
    calls: list[str] = []

    monkeypatch.setattr(
        guard,
        "try_begin_or_reclaim",
        lambda *a, **k: BeginOutcome.BEGUN,
    )
    monkeypatch.setattr(
        lock,
        "acquire",
        lambda resource, *, ttl, owner_id: MagicMock(
            resource=resource, owner_id=owner_id, token=MagicMock(value=1, resource=resource), ttl=ttl
        ),
    )
    monkeypatch.setattr(lock, "release", lambda handle: None)
    monkeypatch.setattr(guard, "mark_done", lambda key, **kw: calls.append(key))

    @idempotent_task(
        guard,
        lock,
        key=lambda batch_id: f"key:{batch_id}",
        lock_resource=lambda batch_id: f"res:{batch_id}",
        idempotency_ttl=timedelta(minutes=5),
        lock_ttl=timedelta(seconds=30),
    )
    def work(batch_id: str) -> dict[str, str]:
        return {"batch_id": batch_id}

    assert work("b1") == {"batch_id": "b1"}
    assert calls == ["key:b1"]


def test_idempotent_task_returns_memo(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    guard = IdempotencyGuard(redis, prefix="t")
    lock = DistributedLock(redis, prefix="t")

    monkeypatch.setattr(
        guard,
        "try_begin_or_reclaim",
        lambda *a, **k: BeginOutcome.ALREADY_DONE,
    )
    monkeypatch.setattr(guard, "get_result", lambda key: {"cached": True})

    @idempotent_task(
        guard,
        lock,
        key=lambda: "k",
        lock_resource=lambda: "r",
        idempotency_ttl=timedelta(minutes=5),
        lock_ttl=timedelta(seconds=30),
    )
    def work() -> None:
        raise AssertionError("should not run")

    assert work() == {"cached": True}


def test_idempotent_task_retries_when_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    guard = IdempotencyGuard(redis, prefix="t")
    lock = DistributedLock(redis, prefix="t")
    task_self = MagicMock()
    task_self.request = object()
    retry_exc = RuntimeError("retry")
    task_self.retry.side_effect = retry_exc

    monkeypatch.setattr(
        guard,
        "try_begin_or_reclaim",
        lambda *a, **k: BeginOutcome.IN_PROGRESS,
    )

    @idempotent_task(
        guard,
        lock,
        key=lambda: "k",
        lock_resource=lambda: "r",
        idempotency_ttl=timedelta(minutes=5),
        lock_ttl=timedelta(seconds=30),
        retry_on_in_progress=True,
        retry_countdown=2.0,
    )
    def work(self) -> None:
        raise AssertionError("should not run")

    with pytest.raises(RuntimeError, match="retry"):
        work(task_self)
    task_self.retry.assert_called_once_with(countdown=2.0)
