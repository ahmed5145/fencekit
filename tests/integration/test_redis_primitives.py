"""Integration tests against real Redis."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

import pytest

from fencekit import (
    DistributedLock,
    FencedOutError,
    FenceGate,
    IdempotencyGuard,
    IdempotencyNotOwned,
    LockNotAcquired,
    LockNotOwned,
    idempotency_key,
)

pytestmark = pytest.mark.integration


def test_lock_acquire_release(redis_client: tuple[Any, str]) -> None:
    client, prefix = redis_client
    lock = DistributedLock(client, prefix=prefix)
    handle = lock.acquire("job-1", ttl=timedelta(seconds=5))
    assert handle.token.value >= 1
    lock.release(handle)


def test_lock_contention(redis_client: tuple[Any, str]) -> None:
    client, prefix = redis_client
    lock = DistributedLock(client, prefix=prefix)
    h1 = lock.acquire("job-contend", ttl=timedelta(seconds=5))
    with pytest.raises(LockNotAcquired):
        lock.acquire("job-contend", ttl=timedelta(seconds=5))
    lock.release(h1)
    h2 = lock.acquire("job-contend", ttl=timedelta(seconds=5))
    assert h2.token.value > h1.token.value
    lock.release(h2)


def test_extend_and_foreign_extend(redis_client: tuple[Any, str]) -> None:
    client, prefix = redis_client
    lock = DistributedLock(client, prefix=prefix)
    handle = lock.acquire("job-ext", ttl=timedelta(seconds=2))
    lock.extend(handle, ttl=timedelta(seconds=5))
    foreign = handle.__class__(
        resource=handle.resource,
        owner_id="not-the-owner",
        token=handle.token,
        ttl=handle.ttl,
    )
    with pytest.raises(LockNotOwned):
        lock.extend(foreign, ttl=timedelta(seconds=5))
    lock.release(handle)


def test_fence_gate_rejects_stale(redis_client: tuple[Any, str]) -> None:
    client, prefix = redis_client
    lock = DistributedLock(client, prefix=prefix)
    fence = FenceGate(client, prefix=prefix)
    h1 = lock.acquire("fenced", ttl=timedelta(milliseconds=200))
    # Abandon without release (crash)
    time.sleep(0.35)
    h2 = lock.acquire("fenced", ttl=timedelta(seconds=5))
    assert h2.token.value > h1.token.value
    fence.check_and_advance(h2.token)
    with pytest.raises(FencedOutError):
        fence.check_and_advance(h1.token)
    lock.release(h2)


def test_idempotency_guard(redis_client: tuple[Any, str]) -> None:
    client, prefix = redis_client
    guard = IdempotencyGuard(client, prefix=prefix)
    key = idempotency_key({"batch": 1}, namespace="analysis")
    assert guard.try_begin(key, ttl=timedelta(seconds=30)) is True
    assert guard.try_begin(key, ttl=timedelta(seconds=30)) is False
    assert guard.status(key) == "pending"
    guard.mark_done(key, ttl=timedelta(seconds=30))
    assert guard.status(key) == "done"
    assert guard.try_begin(key, ttl=timedelta(seconds=30)) is False
    guard.clear(key)
    assert guard.try_begin(key, ttl=timedelta(seconds=30)) is True


def test_mark_done_requires_owner(redis_client: tuple[Any, str]) -> None:
    client, prefix = redis_client
    owner = IdempotencyGuard(client, prefix=prefix, owner_id="worker-a")
    other = IdempotencyGuard(client, prefix=prefix, owner_id="worker-b")
    key = idempotency_key({"batch": 2}, namespace="analysis")
    assert owner.try_begin(key, ttl=timedelta(seconds=30)) is True
    with pytest.raises(IdempotencyNotOwned):
        other.mark_done(key, ttl=timedelta(seconds=30))
    owner.mark_done(key, ttl=timedelta(seconds=30))


def test_batch_analysis_simulation(redis_client: tuple[Any, str]) -> None:
    """End-to-end: idempotency + lock + fence around fake analysis chunks."""
    client, prefix = redis_client
    guard = IdempotencyGuard(client, prefix=prefix)
    lock = DistributedLock(client, prefix=prefix)
    fence = FenceGate(client, prefix=prefix)

    payload = {"game_ids": ["g1", "g2", "g3"], "engine": "sf16"}
    key = idempotency_key(payload, namespace="analysis")
    resource = "analysis:batch-sim"

    assert guard.try_begin(key, ttl=timedelta(minutes=10))
    handle = lock.acquire(resource, ttl=timedelta(seconds=5))
    progress_key = f"{prefix}:progress:{resource}"
    try:
        for i, _game in enumerate(payload["game_ids"], start=1):
            lock.extend(handle, ttl=timedelta(seconds=5))
            fence.check_and_advance(handle.token)
            client.set(progress_key, str(i))
            assert fence.current_max(resource) == handle.token.value
        guard.mark_done(key)
    finally:
        lock.release(handle)

    assert client.get(progress_key) == "3"
    assert guard.try_begin(key, ttl=timedelta(minutes=10)) is False
