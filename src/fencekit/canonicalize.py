"""Deterministic payload canonicalization for idempotency keys."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import TypeAlias

from fencekit.errors import CanonicalizeError

JsonScalar: TypeAlias = str | int | bool | None
JsonValue: TypeAlias = (
    JsonScalar | float | Mapping[str, "JsonValue"] | Sequence["JsonValue"]
)


def _normalize(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizeError(
                "non-finite floats (NaN/Inf) are not allowed in idempotency payloads"
            )
        return value
    if isinstance(value, Mapping):
        out: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizeError(
                    f"mapping keys must be str, got {type(key).__name__}"
                )
            out[key] = _normalize(item)
        return out
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize(item) for item in value]
    raise CanonicalizeError(
        f"unsupported type for canonicalization: {type(value).__name__}; "
        "use JSON-serializable values (datetime must be ISO strings)"
    )


def canonicalize(payload: Mapping[str, object]) -> str:
    """Return a deterministic JSON string for *payload*.

    Rules:

    - Only JSON-serializable mappings, sequences, and scalars.
    - Keys are sorted; separators are compact ``(",", ":")``; ``ensure_ascii=True``.
    - Non-finite floats are rejected.
    - ``datetime`` and other objects are rejected. Pass ISO strings yourself.

    Key stability is the caller's contract: the same business identity must
    serialize the same way across producers.
    """
    if not isinstance(payload, Mapping):
        raise CanonicalizeError("payload must be a mapping")
    normalized = _normalize(dict(payload))
    assert isinstance(normalized, dict)
    try:
        return json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalizeError(str(exc)) from exc


def idempotency_key(payload: Mapping[str, object], *, namespace: str) -> str:
    """Build a deterministic idempotency key from *payload* and *namespace*.

    Returns ``{namespace}:{sha256_hex}``. The idempotency guard and key helpers
    add the Redis prefix.
    """
    if not namespace or not isinstance(namespace, str):
        raise CanonicalizeError("namespace must be a non-empty str")
    if ":" in namespace or any(character.isspace() for character in namespace):
        raise CanonicalizeError("namespace must not contain ':' or whitespace")
    digest = hashlib.sha256(canonicalize(payload).encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"
