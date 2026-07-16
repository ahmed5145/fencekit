"""Unit tests that do not need Redis."""

from __future__ import annotations

from datetime import timedelta

import pytest

from fencekit import (
    FencedOutError,
    FenceKitError,
    FenceToken,
    IdempotencyNotOwned,
    LockHandle,
    LockNotAcquired,
    LockNotOwned,
    TokenExpiredError,
    __version__,
)


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_error_hierarchy() -> None:
    for cls in (
        LockNotAcquired,
        LockNotOwned,
        IdempotencyNotOwned,
        FencedOutError,
        TokenExpiredError,
    ):
        assert issubclass(cls, FenceKitError)


def test_fence_token_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        FenceToken(value=0, resource="job")


def test_lock_handle_token_resource_must_match() -> None:
    token = FenceToken(value=1, resource="job-a")
    with pytest.raises(ValueError, match="match"):
        LockHandle(
            resource="job-b",
            owner_id="owner",
            token=token,
            ttl=timedelta(seconds=1),
        )
