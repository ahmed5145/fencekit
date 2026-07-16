"""Redis-backed fencing gate (storage-layer token enforcement)."""

from __future__ import annotations

from fencekit.client import RedisClient, SyncRedis, integer_response
from fencekit.errors import FencedOutError
from fencekit.keys import DEFAULT_PREFIX, KeySpace
from fencekit.scripts import (
    FENCE_ADVANCE_SCRIPT,
    FENCE_CHECK_SCRIPT,
    FENCED_SET_SCRIPT,
)
from fencekit.types import FenceToken


class FenceGate:
    """Enforce monotonic fencing tokens on a Redis-backed resource gate.

    Use :meth:`set_if_fresh` to combine a Redis ``SET`` and fence comparison in
    one atomic script. :meth:`check` is diagnostic only: a separate write after
    a check has a time-of-check/time-of-use race.

    For PostgreSQL (or other stores), reject stale tokens atomically in the
    same statement as the mutation, for example::

        UPDATE analysis_job
        SET progress = %s, fence_token = %s
        WHERE id = %s AND fence_token <= %s

    Redis alone does not protect writes that bypass this gate.
    """

    def __init__(
        self,
        redis: SyncRedis | RedisClient,
        *,
        prefix: str = DEFAULT_PREFIX,
    ) -> None:
        self._client = redis if isinstance(redis, RedisClient) else RedisClient(redis)
        self._keys = KeySpace(prefix)

    def current_max(self, resource: str) -> int:
        """Return the highest token accepted for *resource* (0 if none)."""
        raw = self._client.get(self._keys.fence_max(resource))
        if raw is None:
            return 0
        return int(raw)

    def check(self, token: FenceToken) -> None:
        """Raise :class:`FencedOutError` if *token* is strictly less than max.

        Equal tokens are allowed (same acquire, multiple writes). This method
        does not advance the gate and must not be used as authorization for a
        later, separate write.
        """
        max_key = self._keys.fence_max(token.resource)
        result = self._client.eval(
            FENCE_CHECK_SCRIPT,
            1,
            max_key,
            token.value,
        )
        if integer_response(result) != 1:
            raise FencedOutError(
                f"token {token.value} for {token.resource!r} is fenced out "
                f"(max={self.current_max(token.resource)})"
            )

    def check_and_advance(self, token: FenceToken) -> None:
        """Accept *token* if ``token >= max``, then set max to *token*.

        Raises :class:`FencedOutError` if a *newer* token was already recorded
        (stale-holder rejection). The same token may write repeatedly.
        """
        max_key = self._keys.fence_max(token.resource)
        result = self._client.eval(
            FENCE_ADVANCE_SCRIPT,
            1,
            max_key,
            token.value,
        )
        if integer_response(result) != 1:
            raise FencedOutError(
                f"token {token.value} for {token.resource!r} is fenced out "
                f"(max={self.current_max(token.resource)})"
            )

    def set_if_fresh(self, token: FenceToken, key: str, value: str) -> None:
        """Atomically set Redis *key* when *token* is not stale.

        The target write and max-token update execute in one Lua script. Raises
        :class:`FencedOutError` without changing *key* when ``token < max``.
        Equal tokens are accepted so one lock acquisition can update progress
        multiple times. The caller owns *key* and must not point it at a
        fencekit coordination key.
        """
        if not key or not isinstance(key, str):
            raise ValueError("key must be a non-empty str")
        max_key = self._keys.fence_max(token.resource)
        if key == max_key:
            raise ValueError("target key must not be the fence max key")
        result = self._client.eval(
            FENCED_SET_SCRIPT,
            2,
            max_key,
            key,
            token.value,
            value,
        )
        if integer_response(result) != 1:
            raise FencedOutError(
                f"token {token.value} for {token.resource!r} is fenced out "
                f"(max={self.current_max(token.resource)})"
            )
