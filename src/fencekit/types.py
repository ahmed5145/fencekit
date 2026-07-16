"""Shared value types for locks and fencing tokens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True, slots=True)
class FenceToken:
    """Monotonic token issued on each successful lock acquire.

    Pass this token to :class:`~fencekit.fence.FenceGate` (and to your own
    storage layer) on every write under the lock.
    """

    value: int
    resource: str

    def __post_init__(self) -> None:
        if self.value < 1:
            raise ValueError("fence token value must be positive")
        if not self.resource:
            raise ValueError("fence token resource must be non-empty")


@dataclass(frozen=True, slots=True)
class LockHandle:
    """Proof of lock ownership returned by :meth:`DistributedLock.acquire`."""

    resource: str
    owner_id: str
    token: FenceToken
    ttl: timedelta

    def __post_init__(self) -> None:
        if not self.owner_id:
            raise ValueError("lock owner_id must be non-empty")
        if self.token.resource != self.resource:
            raise ValueError("lock token resource must match handle resource")
        if self.ttl.total_seconds() <= 0:
            raise ValueError("lock ttl must be positive")
