"""fencekit — Redis idempotency, distributed locks, and fencing tokens."""

from fencekit._version import __version__
from fencekit.canonicalize import canonicalize, idempotency_key
from fencekit.client import RedisClient, SyncRedis
from fencekit.errors import (
    CanonicalizeError,
    FencedOutError,
    FenceKitError,
    IdempotencyNotOwned,
    LockNotAcquired,
    LockNotOwned,
    TokenExpiredError,
)
from fencekit.fence import FenceGate
from fencekit.idempotency import IdempotencyGuard
from fencekit.lock import DistributedLock
from fencekit.types import FenceToken, LockHandle

__all__ = [
    "CanonicalizeError",
    "DistributedLock",
    "FenceGate",
    "FenceKitError",
    "FenceToken",
    "FencedOutError",
    "IdempotencyGuard",
    "IdempotencyNotOwned",
    "LockHandle",
    "LockNotAcquired",
    "LockNotOwned",
    "RedisClient",
    "SyncRedis",
    "TokenExpiredError",
    "__version__",
    "canonicalize",
    "idempotency_key",
]
