"""OpenTelemetry hook factory for fencekit."""

from __future__ import annotations

import importlib.util

from fencekit.hooks import FenceKitHooks, key_label
from fencekit.types import BeginOutcome


def otel_hooks(*, tracer_name: str = "fencekit") -> FenceKitHooks:
    """Return :class:`~fencekit.hooks.FenceKitHooks` that emit OTel spans.

    Requires ``pip install 'fencekit[otel]'`` and a configured tracer provider
    in the host application (SDK setup is caller-owned).

    Span names: ``fencekit.idempotency.begin``, ``fencekit.idempotency.outcome``,
    ``fencekit.idempotency.done``, ``fencekit.lock.acquire``,
    ``fencekit.lock.release``, ``fencekit.fence.advance``,
    ``fencekit.fence.reject``.
    """
    if importlib.util.find_spec("opentelemetry") is None:
        raise ImportError(
            "fencekit.otel requires the otel extra: pip install 'fencekit[otel]'"
        ) from None

    from opentelemetry import trace  # type: ignore[import-not-found,unused-ignore]

    tracer = trace.get_tracer(tracer_name)

    def on_idempotency_begin(key: str, won: bool) -> None:
        with tracer.start_as_current_span("fencekit.idempotency.begin") as span:
            span.set_attribute("fencekit.idempotency.key", key_label(key))
            span.set_attribute("fencekit.idempotency.won", won)

    def on_idempotency_outcome(key: str, outcome: BeginOutcome) -> None:
        with tracer.start_as_current_span("fencekit.idempotency.outcome") as span:
            span.set_attribute("fencekit.idempotency.key", key_label(key))
            span.set_attribute("fencekit.begin.outcome", outcome.value)

    def on_idempotency_done(key: str, stored_result: bool) -> None:
        with tracer.start_as_current_span("fencekit.idempotency.done") as span:
            span.set_attribute("fencekit.idempotency.key", key_label(key))
            span.set_attribute("fencekit.idempotency.stored_result", stored_result)

    def on_lock_acquired(resource: str, token: int) -> None:
        with tracer.start_as_current_span("fencekit.lock.acquire") as span:
            span.set_attribute("fencekit.lock.resource", resource)
            span.set_attribute("fencekit.fence.token", token)

    def on_lock_acquire_failed(resource: str) -> None:
        with tracer.start_as_current_span("fencekit.lock.acquire_failed") as span:
            span.set_attribute("fencekit.lock.resource", resource)

    def on_lock_released(resource: str) -> None:
        with tracer.start_as_current_span("fencekit.lock.release") as span:
            span.set_attribute("fencekit.lock.resource", resource)

    def on_fence_rejected(resource: str, token: int) -> None:
        with tracer.start_as_current_span("fencekit.fence.reject") as span:
            span.set_attribute("fencekit.fence.resource", resource)
            span.set_attribute("fencekit.fence.token", token)

    def on_fence_advanced(resource: str, token: int) -> None:
        with tracer.start_as_current_span("fencekit.fence.advance") as span:
            span.set_attribute("fencekit.fence.resource", resource)
            span.set_attribute("fencekit.fence.token", token)

    return FenceKitHooks(
        on_idempotency_begin=on_idempotency_begin,
        on_idempotency_outcome=on_idempotency_outcome,
        on_idempotency_done=on_idempotency_done,
        on_lock_acquired=on_lock_acquired,
        on_lock_acquire_failed=on_lock_acquire_failed,
        on_lock_released=on_lock_released,
        on_fence_rejected=on_fence_rejected,
        on_fence_advanced=on_fence_advanced,
    )
