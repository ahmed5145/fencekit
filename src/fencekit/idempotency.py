"""Idempotency guard via Redis SET NX EX."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from fencekit.canonicalize import dumps_json, loads_json
from fencekit.client import RedisClient, SyncRedis, integer_response
from fencekit.errors import IdempotencyNotOwned, IdempotencyResultMissing
from fencekit.keys import DEFAULT_PREFIX, KeySpace
from fencekit.lock import DistributedLock
from fencekit.scripts import MARK_DONE_SCRIPT, RECLAIM_PENDING_SCRIPT
from fencekit.types import BeginOutcome

_MISSING = object()


def _ttl_seconds(ttl: timedelta) -> int:
    seconds = int(ttl.total_seconds())
    if seconds < 1:
        raise ValueError("ttl must be at least 1 second for idempotency keys")
    return seconds


class IdempotencyGuard:
    """At-most-once *start* of a named unit of work under Redis availability.

    Uses ``SET key pending:{owner_id} NX EX ttl``. Concurrent workers: only one
    begins, and completion is owner-checked. Optionally memoize a JSON result
    with :meth:`mark_done` / :meth:`get_result` so a redelivery can return the
    prior outcome instead of only observing ``done``.

    Pair with :class:`~fencekit.lock.DistributedLock` and
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

    @property
    def owner_id(self) -> str:
        """Stable owner id for this guard instance (lock pairing and ``mark_done``)."""
        return self._owner_id

    def try_begin(self, key: str, *, ttl: timedelta) -> bool:
        """Return True if this caller won the right to begin work for *key*."""
        redis_key = self._keys.idempotency(key)
        won = self._client.set(
            redis_key,
            f"pending:{self._owner_id}",
            nx=True,
            ex=_ttl_seconds(ttl),
        )
        if won:
            # Drop a leftover memo if a previous done key expired first.
            self._client.delete(self._keys.idempotency_result(key))
        return won

    def try_begin_or_reclaim(
        self,
        key: str,
        *,
        lock: DistributedLock,
        lock_resource: str,
        ttl: timedelta,
    ) -> BeginOutcome:
        """Begin work or reclaim a stale ``pending`` key after a worker crash.

        Use the same ``prefix`` on *lock* as on this guard. *lock_resource* is
        the resource name passed to :meth:`~fencekit.lock.DistributedLock.acquire`.

        Returns :attr:`~fencekit.types.BeginOutcome.ALREADY_DONE` when the key
        is ``done``. Returns :attr:`~fencekit.types.BeginOutcome.IN_PROGRESS`
        when the lock is held (active worker) or the key expired between checks.
        """
        if not isinstance(lock, DistributedLock):
            raise TypeError("lock must be a DistributedLock instance")

        if self.status(key) == "done":
            return BeginOutcome.ALREADY_DONE
        if self.try_begin(key, ttl=ttl):
            return BeginOutcome.BEGUN

        if self.status(key) != "pending":
            if self.status(key) == "done":
                return BeginOutcome.ALREADY_DONE
            if self.try_begin(key, ttl=ttl):
                return BeginOutcome.BEGUN
            return BeginOutcome.IN_PROGRESS

        idem_key = self._keys.idempotency(key)
        lock_key = lock.lock_key(lock_resource)
        code = integer_response(
            self._client.eval(
                RECLAIM_PENDING_SCRIPT,
                2,
                idem_key,
                lock_key,
                self._owner_id,
                _ttl_seconds(ttl),
            )
        )
        if code == 1:
            self._client.delete(self._keys.idempotency_result(key))
            return BeginOutcome.RECLAIMED
        if code == 2:
            return BeginOutcome.ALREADY_DONE
        return BeginOutcome.IN_PROGRESS

    def mark_done(
        self,
        key: str,
        *,
        result: Any = _MISSING,
        ttl: timedelta | None = None,
    ) -> None:
        """Mark *key* as done (refresh TTL if provided).

        When *result* is passed, store it as JSON under a companion Redis key
        with the same TTL as the done marker. ``None`` is a valid memoized
        value. Omit *result* to complete without memoization (and clear any
        previous memo for this key).

        Raises :class:`IdempotencyNotOwned` if the key expired, was reclaimed by
        another guard, or was not begun by this guard. This prevents a stale
        worker from completing a newer worker's attempt.
        """
        redis_key = self._keys.idempotency(key)
        result_key = self._keys.idempotency_result(key)
        ttl_arg = _ttl_seconds(ttl) if ttl is not None else 0
        if result is _MISSING:
            store_result = 0
            result_json = ""
        else:
            store_result = 1
            result_json = dumps_json(result)
        outcome = self._client.eval(
            MARK_DONE_SCRIPT,
            2,
            redis_key,
            result_key,
            self._owner_id,
            ttl_arg,
            store_result,
            result_json,
        )
        if integer_response(outcome) != 1:
            raise IdempotencyNotOwned(
                f"cannot complete idempotency key {key!r}: not owned or expired"
            )

    def get_result(self, key: str) -> Any:
        """Return the memoized result for a completed *key*.

        Raises :class:`IdempotencyResultMissing` when the key is absent, still
        pending, completed without a stored result, or the memo expired.
        """
        if self.status(key) != "done":
            raise IdempotencyResultMissing(
                f"no memoized result for idempotency key {key!r}: "
                "absent, pending, or not done"
            )
        raw = self._client.get(self._keys.idempotency_result(key))
        if raw is None:
            raise IdempotencyResultMissing(
                f"no memoized result for idempotency key {key!r}: "
                "completed without a stored result"
            )
        return loads_json(raw)

    def clear(self, key: str) -> None:
        """Delete the idempotency key and any memoized result (intentional replay)."""
        self._client.delete(
            self._keys.idempotency(key),
            self._keys.idempotency_result(key),
        )

    def status(self, key: str) -> str | None:
        """Return ``pending``, ``done``, or ``None`` if absent."""
        status = self._client.get(self._keys.idempotency(key))
        if status is not None and status.startswith("pending:"):
            return "pending"
        return status
