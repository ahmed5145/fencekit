"""Public exception hierarchy for fencekit."""

from __future__ import annotations


class FenceKitError(Exception):
    """Base error for all fencekit failures."""


class LockNotAcquired(FenceKitError):
    """Raised when a lock could not be acquired within the requested wait."""


class LockNotOwned(FenceKitError):
    """Raised when release/extend is attempted without owning the lock.

    Typical causes: lock TTL expired, another owner holds the key, or the
    handle's owner_id does not match Redis.
    """


class IdempotencyNotOwned(FenceKitError):
    """Raised when a worker cannot complete an idempotency key it does not own."""


class FencedOutError(FenceKitError):
    """Raised when a write presents a fencing token older than the gate max.

    A stale holder receives this error after a newer owner advances the fence.
    """


class TokenExpiredError(FenceKitError):
    """Raised when a lock handle is known to be expired before a write.

    Optional fast-path for callers that track local expiry; Redis remains the
    source of truth for ownership.
    """


class CanonicalizeError(FenceKitError):
    """Raised when a payload cannot be deterministically canonicalized."""
