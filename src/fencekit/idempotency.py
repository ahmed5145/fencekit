"""Idempotency guard via Redis SET NX EX."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fencekit.client import RedisClient, SyncRedis, integer_response
from fencekit.errors import IdempotencyNotOwned
from fencekit.keys import DEFAULT_PREFIX, KeySpace
from fencekit.scripts import MARK_DONE_SCRIPT


def _ttl_seconds(ttl: timedelta) -> int:
    seconds = int(ttl.total_seconds())
    if seconds < 1:
        raise ValueError("ttl must be at least 1 second for idempotency keys")
    return seconds


class IdempotencyGuard:
    """At-most-once *start* of a named unit of work under Redis availability.

    Uses ``SET key pending:{owner_id} NX EX ttl``. Concurrent workers: only one
    begins, and completion is owner-checked. Pair with
    :class:`~fencekit.lock.DistributedLock` and
    :class:`~fencekit.fence.FenceGate` for long jobs with crash/redelivery.
    """

    def __init__(
        self,
        redis: SyncRedis | RedisClient,
        *,
        prefix: str = DEFAULT_PREFIX,
        owner_id: str | None = None,
    ) -> None:
        self._client = redis if isinstance(redis, RedisClient) else RedisClient(redis)
        self._keys = KeySpace(prefix)
        self._owner_id = owner_id or str(uuid.uuid4())

    def try_begin(self, key: str, *, ttl: timedelta) -> bool:
        """Return True if this caller won the right to begin work for *key*."""
        redis_key = self._keys.idempotency(key)
        return self._client.set(
            redis_key,
            f"pending:{self._owner_id}",
            nx=True,
            ex=_ttl_seconds(ttl),
        )

    def mark_done(self, key: str, *, ttl: timedelta | None = None) -> None:
        """Mark *key* as done (refresh TTL if provided).

        Raises :class:`IdempotencyNotOwned` if the key expired, was reclaimed by
        another guard, or was not begun by this guard. This prevents a stale
        worker from completing a newer worker's attempt.
        """
        redis_key = self._keys.idempotency(key)
        ttl_arg = _ttl_seconds(ttl) if ttl is not None else 0
        result = self._client.eval(
            MARK_DONE_SCRIPT,
            1,
            redis_key,
            self._owner_id,
            ttl_arg,
        )
        if integer_response(result) != 1:
            raise IdempotencyNotOwned(
                f"cannot complete idempotency key {key!r}: not owned or expired"
            )

    def clear(self, key: str) -> None:
        """Delete the idempotency key (intentional replay / admin)."""
        self._client.delete(self._keys.idempotency(key))

    def status(self, key: str) -> str | None:
        """Return ``pending``, ``done``, or ``None`` if absent."""
        status = self._client.get(self._keys.idempotency(key))
        if status is not None and status.startswith("pending:"):
            return "pending"
        return status
