"""Redis key naming helpers.

Default prefix is ``fencekit``. Apps sharing a Redis DB should use distinct
prefixes to avoid collisions.
"""

from __future__ import annotations

DEFAULT_PREFIX = "fencekit"


def _validate_segment(name: str, label: str) -> str:
    if not name or not isinstance(name, str):
        raise ValueError(f"{label} must be a non-empty str")
    if any(character.isspace() for character in name):
        raise ValueError(f"{label} must not contain whitespace")
    return name


class KeySpace:
    """Build namespaced Redis keys for locks, fences, and idempotency."""

    def __init__(self, prefix: str = DEFAULT_PREFIX) -> None:
        self.prefix = _validate_segment(prefix, "prefix")

    def idempotency(self, key: str) -> str:
        """Build ``{prefix}:idem:{namespace}:{sha256}`` from a namespaced key."""
        key = _validate_segment(key, "idempotency key")
        return f"{self.prefix}:idem:{key}"

    def idempotency_result(self, key: str) -> str:
        """Build the companion memoized-result key for an idempotency entry."""
        return f"{self.idempotency(key)}:result"

    def lock(self, resource: str) -> str:
        resource = _validate_segment(resource, "resource")
        return f"{self.prefix}:lock:{resource}"

    def fence_seq(self, resource: str) -> str:
        resource = _validate_segment(resource, "resource")
        return f"{self.prefix}:fence:seq:{resource}"

    def fence_max(self, resource: str) -> str:
        resource = _validate_segment(resource, "resource")
        return f"{self.prefix}:fence:max:{resource}"
