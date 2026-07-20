"""Optional Celery task decorator."""

from __future__ import annotations

import functools
import importlib.util
from collections.abc import Callable
from contextlib import suppress
from datetime import timedelta
from typing import Any, TypeVar

from fencekit.errors import IdempotencyResultMissing, LockNotOwned
from fencekit.idempotency import IdempotencyGuard
from fencekit.lock import DistributedLock
from fencekit.types import BeginOutcome

F = TypeVar("F", bound=Callable[..., Any])


def idempotent_task(
    guard: IdempotencyGuard,
    lock: DistributedLock,
    *,
    key: Callable[..., str],
    lock_resource: Callable[..., str],
    idempotency_ttl: timedelta,
    lock_ttl: timedelta,
    store_result: bool = True,
    retry_on_in_progress: bool = False,
    retry_countdown: float = 5.0,
) -> Callable[[F], F]:
    """Wrap a Celery task with idempotency, lock acquire, and optional result memo.

    *key* and *lock_resource* receive the task arguments after any bound ``self``.

    On :attr:`~fencekit.types.BeginOutcome.ALREADY_DONE`, returns a memoized
    result when present, otherwise ``None``. On
    :attr:`~fencekit.types.BeginOutcome.IN_PROGRESS`, returns ``None`` or calls
    ``self.retry`` when *retry_on_in_progress* is True and the task is bound.

    Requires ``pip install 'fencekit[celery]'``.
    """
    if importlib.util.find_spec("celery") is None:
        raise ImportError(
            "fencekit.celery requires the celery extra: pip install 'fencekit[celery]'"
        ) from None

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            task_self = _maybe_task_self(args)
            call_args = args[1:] if task_self is not None else args

            idem_key = key(*call_args, **kwargs)
            resource = lock_resource(*call_args, **kwargs)

            outcome = guard.try_begin_or_reclaim(
                idem_key,
                lock=lock,
                lock_resource=resource,
                ttl=idempotency_ttl,
            )

            if outcome == BeginOutcome.ALREADY_DONE:
                try:
                    return guard.get_result(idem_key)
                except IdempotencyResultMissing:
                    return None

            if outcome == BeginOutcome.IN_PROGRESS:
                if retry_on_in_progress and task_self is not None:
                    raise task_self.retry(countdown=retry_countdown)
                return None

            handle = lock.acquire(
                resource,
                ttl=lock_ttl,
                owner_id=guard.owner_id,
            )
            try:
                result = func(*args, **kwargs)
            except BaseException:
                with suppress(LockNotOwned):
                    lock.release(handle)
                raise
            else:
                try:
                    if store_result:
                        guard.mark_done(
                            idem_key,
                            result=result,
                            ttl=idempotency_ttl,
                        )
                    else:
                        guard.mark_done(idem_key, ttl=idempotency_ttl)
                finally:
                    with suppress(LockNotOwned):
                        lock.release(handle)
                return result

        return wrapper  # type: ignore[return-value]

    return decorator


def _maybe_task_self(args: tuple[Any, ...]) -> Any | None:
    if not args:
        return None
    candidate = args[0]
    if hasattr(candidate, "request") and hasattr(candidate, "retry"):
        return candidate
    return None
