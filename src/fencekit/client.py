"""Sync Redis client protocol and thin redis-py adapter."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


def integer_response(value: object) -> int:
    """Normalize an integer Redis reply without weakening types to ``Any``."""
    if isinstance(value, int):
        return value
    raise TypeError(f"expected integer Redis response, got {type(value).__name__}")


@runtime_checkable
class SyncRedis(Protocol):
    """Minimal sync Redis surface used by fencekit.

    Designed so an asyncio backend can be added later behind a different
    protocol without changing lock/fence algorithms.
    """

    def set(
        self,
        name: str,
        value: str,
        *,
        nx: bool = False,
        xx: bool = False,
        ex: int | None = None,
        px: int | None = None,
    ) -> object: ...

    def get(self, name: str) -> object: ...

    def delete(self, *names: str) -> object: ...

    def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: str | int,
    ) -> object: ...


class RedisClient:
    """Adapter around ``redis.Redis`` with ``decode_responses=True`` semantics.

    Prefer constructing with an existing client::

        RedisClient(redis.Redis.from_url(url, decode_responses=True))
    """

    def __init__(self, redis: SyncRedis) -> None:
        self._redis = redis

    @property
    def raw(self) -> SyncRedis:
        return self._redis

    def set(
        self,
        name: str,
        value: str,
        *,
        nx: bool = False,
        xx: bool = False,
        ex: int | None = None,
        px: int | None = None,
    ) -> bool:
        result = self._redis.set(name, value, nx=nx, xx=xx, ex=ex, px=px)
        # redis-py returns True/None depending on version and NX
        return bool(result)

    def get(self, name: str) -> str | None:
        value = self._redis.get(name)
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    def delete(self, *names: str) -> int:
        return integer_response(self._redis.delete(*names))

    def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: str | int,
    ) -> object:
        return self._redis.eval(script, numkeys, *keys_and_args)
