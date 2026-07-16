"""Fast lock API unit tests with scripted Redis replies."""

from __future__ import annotations

from datetime import timedelta

import pytest

from fencekit import DistributedLock, LockNotAcquired, LockNotOwned


class ScriptedRedis:
    """Minimal SyncRedis test double; real Lua behavior is integration-tested."""

    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)

    def set(
        self,
        name: str,
        value: str,
        *,
        nx: bool = False,
        xx: bool = False,
        ex: int | None = None,
        px: int | None = None,
    ) -> object:
        del name, value, nx, xx, ex, px
        return self.responses.pop(0)

    def get(self, name: str) -> object:
        del name
        return self.responses.pop(0)

    def delete(self, *names: str) -> object:
        del names
        return self.responses.pop(0)

    def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: str | int,
    ) -> object:
        del script, numkeys, keys_and_args
        return self.responses.pop(0)


def test_acquire_and_release_happy_path() -> None:
    redis = ScriptedRedis(7, 1)
    lock = DistributedLock(redis)

    handle = lock.acquire("job", ttl=timedelta(seconds=5), owner_id="worker")

    assert handle.token.value == 7
    assert handle.owner_id == "worker"
    lock.release(handle)


def test_contention_raises_lock_not_acquired() -> None:
    lock = DistributedLock(ScriptedRedis(None))

    with pytest.raises(LockNotAcquired):
        lock.acquire("job", ttl=timedelta(seconds=5))


def test_expired_handle_cannot_release() -> None:
    lock = DistributedLock(ScriptedRedis(8, 0))
    handle = lock.acquire("job", ttl=timedelta(seconds=5))

    with pytest.raises(LockNotOwned):
        lock.release(handle)


def test_context_manager_releases() -> None:
    lock = DistributedLock(ScriptedRedis(9, 1))

    with lock.hold("job", ttl=timedelta(seconds=5)) as handle:
        assert handle.token.value == 9
