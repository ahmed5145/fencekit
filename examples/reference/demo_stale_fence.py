"""Stale lock holder rejected after TTL (requires local Redis).

Simulates: worker A acquires lock, pauses past TTL, worker B takes over with a
higher fencing token, worker A's write is rejected.

Run from repo root::

    docker compose -f examples/reference/docker-compose.yml up -d
    pip install -e .
    python examples/reference/demo_stale_fence.py
"""

from __future__ import annotations

import sys
import time
from datetime import timedelta

from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from fencekit import DistributedLock, FencedOutError, FenceGate

REDIS_URL = "redis://localhost:6379/0"
PREFIX = "fk-demo-fence"
RESOURCE = "analysis:batch-1"
STATUS_KEY = f"{PREFIX}:status:{RESOURCE}"


def main() -> int:
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except RedisConnectionError:
        print("Redis not reachable at", REDIS_URL)
        print("Start it: docker compose -f examples/reference/docker-compose.yml up -d")
        return 1

    lock = DistributedLock(client, prefix=PREFIX)
    fence = FenceGate(client, prefix=PREFIX)

    print("Worker A acquires lock (TTL 1s)...")
    handle_a = lock.acquire(RESOURCE, ttl=timedelta(seconds=1))
    print(f"  token={handle_a.token.value}")

    print("Worker A pauses past lease TTL...")
    time.sleep(1.25)

    print("Worker B acquires lock after expiry...")
    handle_b = lock.acquire(RESOURCE, ttl=timedelta(seconds=30))
    print(f"  token={handle_b.token.value} (higher than A)")
    fence.set_if_fresh(handle_b.token, STATUS_KEY, "written-by-B")
    print("  B wrote status:", client.get(STATUS_KEY))

    print("Worker A wakes up and tries to write with stale token...")
    try:
        fence.set_if_fresh(handle_a.token, STATUS_KEY, "written-by-stale-A")
    except FencedOutError:
        print("  FencedOutError (expected): stale holder rejected")
    else:
        print("  ERROR: stale write should have been rejected")
        return 1

    print("Final status:", client.get(STATUS_KEY))
    lock.release(handle_b)

    # Cleanup demo keys
    for key in client.scan_iter(match=f"{PREFIX}:*"):
        client.delete(key)

    print("\nDone. Stale worker could not overwrite B's progress.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
