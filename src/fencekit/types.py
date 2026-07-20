"""Shared value types for locks and fencing tokens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum


class BeginOutcome(str, Enum):
    """Result of :meth:`~fencekit.idempotency.IdempotencyGuard.try_begin_or_reclaim`."""

    BEGUN = "begun"
    """This caller won a fresh ``SET NX`` and may run the job."""

    RECLAIMED = "reclaimed"
    """The key was ``pending`` with no lock held; ownership moved to this caller."""

    ALREADY_DONE = "already_done"
    """The key is ``done``; call :meth:`~fencekit.idempotency.IdempotencyGuard.get_result`."""

    IN_PROGRESS = "in_progress"
    """Another worker holds the lock or the key state is ambiguous; do not start."""


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
