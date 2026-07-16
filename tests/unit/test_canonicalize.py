"""Unit tests for canonicalize / idempotency_key (no Redis)."""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fencekit.canonicalize import canonicalize, idempotency_key
from fencekit.errors import CanonicalizeError
from fencekit.keys import KeySpace


def test_canonicalize_sorts_keys() -> None:
    a = canonicalize({"b": 1, "a": 2})
    b = canonicalize({"a": 2, "b": 1})
    assert a == b == '{"a":2,"b":1}'


def test_idempotency_key_stable_under_key_order() -> None:
    k1 = idempotency_key(
        {"game_ids": ["x", "y"], "engine": "sf16"},
        namespace="analysis",
    )
    k2 = idempotency_key(
        {"engine": "sf16", "game_ids": ["x", "y"]},
        namespace="analysis",
    )
    assert k1 == k2
    assert k1.startswith("analysis:")


def test_idempotency_key_differs_for_payload() -> None:
    a = idempotency_key({"n": 1}, namespace="ns")
    b = idempotency_key({"n": 2}, namespace="ns")
    assert a != b


def test_reject_nan() -> None:
    with pytest.raises(CanonicalizeError):
        canonicalize({"x": float("nan")})


def test_reject_datetime_objects() -> None:
    import datetime

    with pytest.raises(CanonicalizeError):
        canonicalize({"when": datetime.datetime(2026, 1, 1)})


def test_reject_bad_namespace() -> None:
    with pytest.raises(CanonicalizeError):
        idempotency_key({"a": 1}, namespace="bad:ns")


def test_keyspace_patterns() -> None:
    ks = KeySpace("fencekit")
    assert ks.lock("res") == "fencekit:lock:res"
    assert ks.fence_seq("res") == "fencekit:fence:seq:res"
    assert ks.fence_max("res") == "fencekit:fence:max:res"
    assert ks.idempotency("ns:abc") == "fencekit:idem:ns:abc"


@given(
    st.dictionaries(
        st.text(min_size=1, max_size=6, alphabet="abcdefghijklmnopqrstuvwxyz"),
        st.one_of(
            st.none(),
            st.booleans(),
            st.integers(min_value=-1000, max_value=1000),
            st.floats(allow_nan=False, allow_infinity=False, width=32),
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", max_size=12),
        ),
        max_size=4,
    )
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_canonicalize_deterministic(payload: dict[str, object]) -> None:
    assert canonicalize(payload) == canonicalize(dict(reversed(list(payload.items()))))
