"""Distributed lock with atomic fencing-token issuance."""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import timedelta

from fencekit.client import RedisClient, SyncRedis, integer_response
from fencekit.errors import LockNotAcquired, LockNotOwned
from fencekit.hooks import FenceKitHooks
from fencekit.keys import DEFAULT_PREFIX, KeySpace
from fencekit.scripts import ACQUIRE_SCRIPT, EXTEND_SCRIPT, RELEASE_SCRIPT
from fencekit.types import FenceToken, LockHandle

_DEFAULT_RETRY_INTERVAL = timedelta(milliseconds=50)


def _ttl_ms(ttl: timedelta) -> int:
    ms = int(ttl.total_seconds() * 1000)
    if ms < 1:
        raise ValueError("ttl must be at least 1ms")
    return ms


class DistributedLock:
    """Single-instance Redis lock with fencing tokens.

    Acquire uses a Lua script that ``SET``s the lock ``NX PX`` and ``INCR``s the
    fence sequence in one atomic step. Release/extend only succeed if the
    caller still owns the lock key.

    This is **not** Redlock. See DESIGN.md for guarantees and caveats.
    """

    def __init__(
        self,
        redis: SyncRedis | RedisClient,
        *,
        prefix: str = DEFAULT_PREFIX,
        hooks: FenceKitHooks | None = None,
    ) -> None:
        self._client = redis if isinstance(redis, RedisClient) else RedisClient(redis)
        self._keys = KeySpace(prefix)
        self._hooks = hooks or FenceKitHooks()

    def acquire(
        self,
        resource: str,
        *,
        ttl: timedelta,
        owner_id: str | None = None,
        blocking: bool = False,
        wait: timedelta | None = None,
        retry_interval: timedelta = _DEFAULT_RETRY_INTERVAL,
    ) -> LockHandle:
        """Acquire *resource* and return a :class:`LockHandle` with a fence token.

        If *blocking* is False (default), raises :class:`LockNotAcquired` on
        contention. If True, retries until *wait* elapses (required when
        blocking).
        """
        if retry_interval.total_seconds() <= 0:
            raise ValueError("retry_interval must be positive")
        owner = owner_id or str(uuid.uuid4())
        deadline: float | None = None
        if blocking:
            if wait is None:
                raise ValueError("wait is required when blocking=True")
            if wait.total_seconds() < 0:
                raise ValueError("wait must not be negative")
            deadline = time.monotonic() + wait.total_seconds()

        while True:
            handle = self._try_acquire(resource, ttl=ttl, owner_id=owner)
            if handle is not None:
                return handle
            if not blocking or deadline is None:
                self._hooks.lock_acquire_failed(resource)
                raise LockNotAcquired(f"could not acquire lock for {resource!r}")
            if time.monotonic() >= deadline:
                self._hooks.lock_acquire_failed(resource)
                raise LockNotAcquired(
                    f"timed out waiting for lock {resource!r} after {wait}"
                )
            time.sleep(retry_interval.total_seconds())

    def _try_acquire(
        self,
        resource: str,
        *,
        ttl: timedelta,
        owner_id: str,
    ) -> LockHandle | None:
        lock_key = self._keys.lock(resource)
        seq_key = self._keys.fence_seq(resource)
        result = self._client.eval(
            ACQUIRE_SCRIPT,
            2,
            lock_key,
            seq_key,
            owner_id,
            _ttl_ms(ttl),
        )
        if result is None or result is False:
            return None
        token_value = integer_response(result)
        self._hooks.lock_acquired(resource, token_value)
        return LockHandle(
            resource=resource,
            owner_id=owner_id,
            token=FenceToken(value=token_value, resource=resource),
            ttl=ttl,
        )

    def release(self, handle: LockHandle) -> None:
        """Release *handle* if still owned; raise :class:`LockNotOwned` otherwise."""
        lock_key = self._keys.lock(handle.resource)
        result = self._client.eval(
            RELEASE_SCRIPT,
            1,
            lock_key,
            handle.owner_id,
        )
        if integer_response(result) != 1:
            raise LockNotOwned(
                f"cannot release lock {handle.resource!r}: not owned or expired"
            )
        self._hooks.lock_released(handle.resource)

    def extend(self, handle: LockHandle, *, ttl: timedelta) -> None:
        """Extend lock TTL if still owned (heartbeat)."""
        lock_key = self._keys.lock(handle.resource)
        result = self._client.eval(
            EXTEND_SCRIPT,
            1,
            lock_key,
            handle.owner_id,
            _ttl_ms(ttl),
        )
        if integer_response(result) != 1:
            raise LockNotOwned(
                f"cannot extend lock {handle.resource!r}: not owned or expired"
            )

    @contextmanager
    def hold(
        self,
        resource: str,
        *,
        ttl: timedelta,
        owner_id: str | None = None,
        blocking: bool = False,
        wait: timedelta | None = None,
    ) -> Iterator[LockHandle]:
        """Context-manager helper: ``with lock.hold("res", ttl=...) as handle``."""
        handle = self.acquire(
            resource,
            ttl=ttl,
            owner_id=owner_id,
            blocking=blocking,
            wait=wait,
        )
        try:
            yield handle
        except BaseException:
            # Preserve the critical-section exception if the lease also expired.
            with suppress(LockNotOwned):
                self.release(handle)
            raise
        else:
            self.release(handle)

    def lock_key(self, resource: str) -> str:
        """Redis key for *resource* (pair with idempotency pending reclaim)."""
        return self._keys.lock(resource)
