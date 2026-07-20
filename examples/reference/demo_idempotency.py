"""Idempotency + result memo demo (requires local Redis).

Run from repo root::

    docker compose -f examples/reference/docker-compose.yml up -d
    pip install -e .
    python examples/reference/demo_idempotency.py
"""

from __future__ import annotations

import sys
from datetime import timedelta

from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from fencekit import IdempotencyGuard, IdempotencyResultMissing, idempotency_key

REDIS_URL = "redis://localhost:6379/0"
PREFIX = "fk-demo-idem"


def main() -> int:
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except RedisConnectionError:
        print("Redis not reachable at", REDIS_URL)
        print(
            "Start Redis on localhost:6379 (Docker compose file in this folder, "
            "WSL, or a local Redis install)."
        )
        return 1

    guard = IdempotencyGuard(client, prefix=PREFIX)
    key = idempotency_key({"demo": "batch-1", "engine": "sf16"}, namespace="analysis")
    ttl = timedelta(minutes=5)

    print("1) First worker try_begin ->", guard.try_begin(key, ttl=ttl))
    print("2) Duplicate try_begin ->", guard.try_begin(key, ttl=ttl))

    result = {"report_id": 42, "status": "done"}
    guard.mark_done(key, result=result, ttl=ttl)
    print("3) Memoized result ->", guard.get_result(key))

    print("4) Redelivery try_begin ->", guard.try_begin(key, ttl=ttl))
    print("5) Redelivery get_result ->", guard.get_result(key))

    try:
        guard.get_result("analysis:nonexistent-key")
    except IdempotencyResultMissing as exc:
        print("6) Missing key raises IdempotencyResultMissing:", exc)

    guard.clear(key)
    print("7) After clear, try_begin ->", guard.try_begin(key, ttl=ttl))
    guard.clear(key)
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
