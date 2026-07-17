"""Storage-layer fencing helpers for stores outside Redis."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from fencekit.errors import FencedOutError
from fencekit.types import FenceToken


class SupportsFencedUpdate(Protocol):
    """Minimal QuerySet-shaped interface used by :func:`fenced_update`.

    Django's ``QuerySet`` satisfies this protocol. Tests can fake it without
    importing Django.
    """

    def filter(self, *args: Any, **kwargs: Any) -> SupportsFencedUpdate:
        """Return a narrowed queryset (Django ``filter`` semantics)."""
        ...

    def update(self, **kwargs: Any) -> int:
        """Apply field updates; return the number of rows modified."""
        ...


def fenced_update(
    queryset: SupportsFencedUpdate,
    token: FenceToken,
    *,
    updates: Mapping[str, Any],
    fence_field: str = "fence_token",
    raise_on_stale: bool = False,
) -> bool:
    """Atomically apply *updates* when the row fence is not newer than *token*.

    Builds the Django / SQL pattern::

        UPDATE ...
        SET <updates>, fence_token = <token.value>
        WHERE ... AND fence_token <= <token.value>

    Pass a queryset already narrowed to the target row(s), for example
    ``AnalysisJob.objects.filter(pk=job_id)``. The helper adds the
    ``fence_field__lte`` predicate and writes ``fence_field`` from *token*.

    Returns ``True`` when at least one row was updated. Returns ``False`` when
    no row matched (missing row or a newer fence already stored). When
    *raise_on_stale* is ``True`` and nothing matched, raises
    :class:`~fencekit.errors.FencedOutError`. Callers that must distinguish
    "missing" from "stale" should check existence before calling this helper.

    Parameters
    ----------
    queryset:
        Django ``QuerySet`` (or compatible fake) already filtered to the
        row(s) being written.
    token:
        Fencing token from a successful lock acquire.
    updates:
        Field names and values to write. Must be non-empty and must not
        include *fence_field* (that column is set from *token*).
    fence_field:
        Integer column that stores the highest accepted token for the row.
    raise_on_stale:
        If ``True``, raise instead of returning ``False`` when no row updates.
    """
    if not fence_field:
        raise ValueError("fence_field must be a non-empty str")
    if not updates:
        raise ValueError("updates must be non-empty")
    if fence_field in updates:
        raise ValueError(f"{fence_field!r} is set from the token; omit it from updates")

    payload = dict(updates)
    payload[fence_field] = token.value
    lte_lookup = {f"{fence_field}__lte": token.value}
    updated = int(queryset.filter(**lte_lookup).update(**payload))
    if updated > 0:
        return True
    if raise_on_stale:
        raise FencedOutError(
            f"token {token.value} for {token.resource!r} did not update any "
            f"row (missing or fenced out on {fence_field!r})"
        )
    return False
