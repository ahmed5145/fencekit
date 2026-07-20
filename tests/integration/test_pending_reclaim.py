"""Integration tests for pending reclaim after worker crash."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from fencekit import (
    DistributedLock,
    IdempotencyGuard,
    IdempotencyNotOwned,
    idempotency_key,
)
from fencekit.types import BeginOutcome

pytestmark = pytest.mark.integration


def test_try_begin_or_reclaim_fresh(redis_client: tuple[Any, str]) -> None:
    client, prefix = redis_client
    guard = IdempotencyGuard(client, prefix=prefix)
    lock = DistributedLock(client, prefix=prefix)
    key = idempotency_key({"batch": "reclaim-fresh"}, namespace="analysis")
    resource = "analysis:reclaim-fresh"

    assert guard.try_begin_or_reclaim(
        key, lock=lock, lock_resource=resource, ttl=timedelta(seconds=30)
    ) == BeginOutcome.BEGUN


def test_try_begin_or_reclaim_already_done(redis_client: tuple[Any, str]) -> None:
    client, prefix = redis_client
    guard = IdempotencyGuard(client, prefix=prefix)
    lock = DistributedLock(client, prefix=prefix)
    key = idempotency_key({"batch": "reclaim-done"}, namespace="analysis")
    resource = "analysis:reclaim-done"

    assert guard.try_begin(key, ttl=timedelta(seconds=30))
    guard.mark_done(key, result={"ok": True}, ttl=timedelta(seconds=30))

    assert guard.try_begin_or_reclaim(
        key, lock=lock, lock_resource=resource, ttl=timedelta(seconds=30)
    ) == BeginOutcome.ALREADY_DONE
    assert guard.get_result(key) == {"ok": True}


def test_reclaim_after_crash_without_lock(redis_client: tuple[Any, str]) -> None:
    """Worker A began and died without holding the lock; B reclaims."""
    client, prefix = redis_client
    dead = IdempotencyGuard(client, prefix=prefix, owner_id="worker-dead")
    alive = IdempotencyGuard(client, prefix=prefix, owner_id="worker-alive")
    lock = DistributedLock(client, prefix=prefix)
    key = idempotency_key({"batch": "reclaim-crash"}, namespace="analysis")
    resource = "analysis:reclaim-crash"

    assert dead.try_begin(key, ttl=timedelta(seconds=30))

    outcome = alive.try_begin_or_reclaim(
        key, lock=lock, lock_resource=resource, ttl=timedelta(seconds=30)
    )
    assert outcome == BeginOutcome.RECLAIMED
    alive.mark_done(key, result={"recovered": True}, ttl=timedelta(seconds=30))
    assert alive.get_result(key) == {"recovered": True}


def test_reclaim_blocked_while_lock_held(redis_client: tuple[Any, str]) -> None:
    client, prefix = redis_client
    owner = IdempotencyGuard(client, prefix=prefix, owner_id="worker-a")
    other = IdempotencyGuard(client, prefix=prefix, owner_id="worker-b")
    lock = DistributedLock(client, prefix=prefix)
    key = idempotency_key({"batch": "reclaim-active"}, namespace="analysis")
    resource = "analysis:reclaim-active"

    assert owner.try_begin(key, ttl=timedelta(seconds=30))
    handle = lock.acquire(resource, ttl=timedelta(seconds=30))
    try:
        assert other.try_begin_or_reclaim(
            key, lock=lock, lock_resource=resource, ttl=timedelta(seconds=30)
        ) == BeginOutcome.IN_PROGRESS
    finally:
        lock.release(handle)


def test_dead_owner_cannot_mark_done_after_reclaim(
    redis_client: tuple[Any, str],
) -> None:
    client, prefix = redis_client
    dead = IdempotencyGuard(client, prefix=prefix, owner_id="worker-dead")
    alive = IdempotencyGuard(client, prefix=prefix, owner_id="worker-alive")
    lock = DistributedLock(client, prefix=prefix)
    key = idempotency_key({"batch": "reclaim-owner"}, namespace="analysis")
    resource = "analysis:reclaim-owner"

    assert dead.try_begin(key, ttl=timedelta(seconds=30))
    assert alive.try_begin_or_reclaim(
        key, lock=lock, lock_resource=resource, ttl=timedelta(seconds=30)
    ) == BeginOutcome.RECLAIMED

    with pytest.raises(IdempotencyNotOwned):
        dead.mark_done(key, ttl=timedelta(seconds=30))

    alive.mark_done(key, ttl=timedelta(seconds=30))
