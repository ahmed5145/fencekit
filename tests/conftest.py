"""Shared fixtures for fencekit tests."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

REDIS_URL = os.environ.get("FENCEKIT_REDIS_URL")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: tests that require a real Redis instance (FENCEKIT_REDIS_URL)",
    )


@pytest.fixture
def redis_url() -> str:
    if not REDIS_URL:
        pytest.skip("FENCEKIT_REDIS_URL not set; skipping Redis integration tests")
    return REDIS_URL


@pytest.fixture
def redis_client(redis_url: str) -> Iterator[object]:
    from redis import Redis

    client = Redis.from_url(redis_url, decode_responses=True)
    try:
        client.ping()
    except Exception as exc:
        pytest.skip(f"Redis not reachable at {redis_url}: {exc}")
    # Isolate keys per test
    prefix = f"fk-test-{uuid.uuid4().hex[:12]}"
    yield client, prefix
    # Best-effort cleanup of this test's keys
    for key in client.scan_iter(match=f"{prefix}:*"):
        client.delete(key)
    client.close()
