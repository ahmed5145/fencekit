"""Property / contention tests for IdempotencyGuard (requires Redis)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fencekit import IdempotencyGuard, idempotency_key

pytestmark = pytest.mark.integration


@given(worker_count=st.integers(min_value=2, max_value=20))
@settings(
    max_examples=6,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_concurrent_try_begin_exactly_one(
    redis_client: tuple[Any, str],
    worker_count: int,
) -> None:
    client, prefix = redis_client
    guard = IdempotencyGuard(client, prefix=prefix)
    key = idempotency_key({"job": "concurrent"}, namespace="idem")

    def attempt() -> bool:
        return guard.try_begin(key, ttl=timedelta(seconds=30))

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        results = list(pool.map(lambda _: attempt(), range(worker_count)))

    assert sum(1 for r in results if r) == 1
    assert guard.status(key) == "pending"
    guard.clear(key)


@given(ttl_seconds=st.integers(min_value=1, max_value=60))
@settings(
    max_examples=5,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_mark_done_blocks_begin(
    redis_client: tuple[Any, str],
    ttl_seconds: int,
) -> None:
    client, prefix = redis_client
    guard = IdempotencyGuard(client, prefix=prefix)
    key = idempotency_key({"job": "done"}, namespace="idem")
    ttl = timedelta(seconds=ttl_seconds)
    assert guard.try_begin(key, ttl=ttl)
    guard.mark_done(key, ttl=ttl)
    assert guard.try_begin(key, ttl=ttl) is False
    guard.clear(key)


@given(
    report_id=st.integers(min_value=1, max_value=10_000),
    games=st.lists(st.text(min_size=1, max_size=8), max_size=5),
)
@settings(
    max_examples=8,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_memoized_result_round_trip(
    redis_client: tuple[Any, str],
    report_id: int,
    games: list[str],
) -> None:
    client, prefix = redis_client
    guard = IdempotencyGuard(client, prefix=prefix)
    key = idempotency_key({"job": "memo", "report_id": report_id}, namespace="idem")
    result = {"report_id": report_id, "games": games}
    assert guard.try_begin(key, ttl=timedelta(seconds=30))
    guard.mark_done(key, result=result, ttl=timedelta(seconds=30))
    assert guard.get_result(key) == result
    assert guard.try_begin(key, ttl=timedelta(seconds=30)) is False
    guard.clear(key)
