"""Optional observability hooks for fencekit operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fencekit.types import BeginOutcome


@dataclass
class FenceKitHooks:
    """Callbacks for logging, metrics, or tracing around fencekit APIs.

    All callbacks are optional. Hook bodies must not raise: fencekit swallows
    exceptions so observability cannot break job processing.
    """

    on_idempotency_begin: Callable[[str, bool], None] | None = None
    on_idempotency_outcome: Callable[[str, BeginOutcome], None] | None = None
    on_idempotency_done: Callable[[str, bool], None] | None = None
    on_lock_acquired: Callable[[str, int], None] | None = None
    on_lock_acquire_failed: Callable[[str], None] | None = None
    on_lock_released: Callable[[str], None] | None = None
    on_fence_rejected: Callable[[str, int], None] | None = None
    on_fence_advanced: Callable[[str, int], None] | None = None

    def idempotency_begin(self, key: str, won: bool) -> None:
        _safe_call(self.on_idempotency_begin, key, won)

    def idempotency_outcome(self, key: str, outcome: BeginOutcome) -> None:
        _safe_call(self.on_idempotency_outcome, key, outcome)

    def idempotency_done(self, key: str, stored_result: bool) -> None:
        _safe_call(self.on_idempotency_done, key, stored_result)

    def lock_acquired(self, resource: str, token: int) -> None:
        _safe_call(self.on_lock_acquired, resource, token)

    def lock_acquire_failed(self, resource: str) -> None:
        _safe_call(self.on_lock_acquire_failed, resource)

    def lock_released(self, resource: str) -> None:
        _safe_call(self.on_lock_released, resource)

    def fence_rejected(self, resource: str, token: int) -> None:
        _safe_call(self.on_fence_rejected, resource, token)

    def fence_advanced(self, resource: str, token: int) -> None:
        _safe_call(self.on_fence_advanced, resource, token)


def _safe_call(callback: Callable[..., None] | None, *args: object) -> None:
    if callback is None:
        return
    try:
        callback(*args)
    except Exception:
        return


def key_label(key: str, *, suffix_len: int = 12) -> str:
    """Short label for telemetry (avoids logging full idempotency keys)."""
    if len(key) <= suffix_len:
        return key
    return f"...{key[-suffix_len:]}"
