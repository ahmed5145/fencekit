"""Property tests: fencing, expiry, crash-restart (requires Redis)."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fencekit import (
    DistributedLock,
    FencedOutError,
    FenceGate,
    LockNotAcquired,
    LockNotOwned,
)

pytestmark = pytest.mark.integration


@given(ttl_ms=st.integers(min_value=80, max_value=180))
@settings(
    max_examples=4,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_crash_restart_stale_token_fenced(
    redis_client: tuple[Any, str],
    ttl_ms: int,
) -> None:
    """Interview artifact: abandon lock → TTL → new token → stale rejected."""
    client, prefix = redis_client
    lock = DistributedLock(client, prefix=prefix)
    fence = FenceGate(client, prefix=prefix)
    resource = "crash-restart"

    stale = lock.acquire(resource, ttl=timedelta(milliseconds=ttl_ms))
    # Simulate process death: abandon without release
    time.sleep((ttl_ms + 100) / 1000)
    fresh = lock.acquire(resource, ttl=timedelta(seconds=5))
    assert fresh.token.value == stale.token.value + 1

    progress_key = f"{prefix}:progress:{resource}"
    fence.set_if_fresh(fresh.token, progress_key, "fresh")
    with pytest.raises(FencedOutError):
        fence.set_if_fresh(stale.token, progress_key, "stale")
    assert client.get(progress_key) == "fresh"
    with pytest.raises(FencedOutError):
        fence.check(stale.token)
    with pytest.raises(LockNotOwned):
        lock.extend(stale, ttl=timedelta(seconds=5))
    with pytest.raises(LockNotOwned):
        lock.release(stale)
    lock.release(fresh)


@given(worker_count=st.integers(min_value=2, max_value=12))
@settings(
    max_examples=5,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_concurrent_acquire_one_winner(
    redis_client: tuple[Any, str],
    worker_count: int,
) -> None:
    client, prefix = redis_client
    lock = DistributedLock(client, prefix=prefix)
    resource = "concurrent-acq"

    def attempt() -> int | None:
        try:
            h = lock.acquire(resource, ttl=timedelta(seconds=3))
            return h.token.value
        except LockNotAcquired:
            return None

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        results = list(pool.map(lambda _: attempt(), range(worker_count)))

    winners = [t for t in results if t is not None]
    assert len(winners) == 1
    client.delete(f"{prefix}:lock:{resource}")


@given(rounds=st.integers(min_value=1, max_value=5))
@settings(
    max_examples=5,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_fencing_tokens_monotonic_on_abandon(
    redis_client: tuple[Any, str],
    rounds: int,
) -> None:
    client, prefix = redis_client
    lock = DistributedLock(client, prefix=prefix)
    fence = FenceGate(client, prefix=prefix)
    resource = f"mono-{rounds}-{time.time_ns()}"
    last = 0
    for _ in range(rounds):
        handle = lock.acquire(resource, ttl=timedelta(milliseconds=100))
        assert handle.token.value > last
        last = handle.token.value
        fence.check_and_advance(handle.token)
        # abandon (crash) — do not release
        time.sleep(0.15)
    assert fence.current_max(resource) == last


@given(ttl_ms=st.integers(min_value=80, max_value=180))
@settings(
    max_examples=4,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_lock_expiry_during_critical_section(
    redis_client: tuple[Any, str],
    ttl_ms: int,
) -> None:
    client, prefix = redis_client
    lock = DistributedLock(client, prefix=prefix)
    fence = FenceGate(client, prefix=prefix)
    resource = "expiry-cs"

    holder = lock.acquire(resource, ttl=timedelta(milliseconds=ttl_ms))
    time.sleep((ttl_ms + 100) / 1000)
    other = lock.acquire(resource, ttl=timedelta(seconds=3))
    fence.check_and_advance(other.token)

    with pytest.raises(LockNotOwned):
        lock.extend(holder, ttl=timedelta(seconds=3))
    with pytest.raises(LockNotOwned):
        lock.release(holder)
    with pytest.raises(FencedOutError):
        fence.check_and_advance(holder.token)

    lock.release(other)


def test_extend_heartbeat_keeps_ownership(redis_client: tuple[Any, str]) -> None:
    client, prefix = redis_client
    lock = DistributedLock(client, prefix=prefix)
    handle = lock.acquire("heartbeat", ttl=timedelta(milliseconds=200))
    for _ in range(5):
        time.sleep(0.08)
        lock.extend(handle, ttl=timedelta(milliseconds=200))
    lock.release(handle)
