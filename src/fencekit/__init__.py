"""Redis idempotency and fenced locks for background jobs."""

from fencekit._version import __version__
from fencekit.canonicalize import canonicalize, dumps_json, idempotency_key, loads_json
from fencekit.client import RedisClient, SyncRedis
from fencekit.errors import (
    CanonicalizeError,
    FencedOutError,
    FenceKitError,
    IdempotencyNotOwned,
    IdempotencyResultMissing,
    LockNotAcquired,
    LockNotOwned,
    TokenExpiredError,
)
from fencekit.fence import FenceGate
from fencekit.hooks import FenceKitHooks
from fencekit.idempotency import IdempotencyGuard
from fencekit.lock import DistributedLock
from fencekit.storage import SupportsFencedUpdate, fenced_update
from fencekit.types import BeginOutcome, FenceToken, LockHandle

__all__ = [
    "BeginOutcome",
    "CanonicalizeError",
    "DistributedLock",
    "FenceKitHooks",
    "FenceGate",
    "FenceKitError",
    "FenceToken",
    "FencedOutError",
    "IdempotencyGuard",
    "IdempotencyNotOwned",
    "IdempotencyResultMissing",
    "LockHandle",
    "LockNotAcquired",
    "LockNotOwned",
    "RedisClient",
    "SupportsFencedUpdate",
    "SyncRedis",
    "TokenExpiredError",
    "__version__",
    "canonicalize",
    "dumps_json",
    "fenced_update",
    "idempotency_key",
    "loads_json",
]
