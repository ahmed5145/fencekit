# fencekit

[![CI](https://github.com/ahmed5145/fencekit/actions/workflows/ci.yml/badge.svg)](https://github.com/ahmed5145/fencekit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/fencekit.svg)](https://pypi.org/project/fencekit/)
[![Python](https://img.shields.io/pypi/pyversions/fencekit.svg)](https://pypi.org/project/fencekit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Redis-backed idempotency and fenced distributed locks for background jobs.

Celery with `acks_late` redelivers work after a worker crash. Redis gives you
`SET NX` and Lua. fencekit wraps those into tested pieces:

| Piece | Problem it solves |
|-------|-------------------|
| `IdempotencyGuard` | Double-start / redelivery of the same logical job |
| `DistributedLock` + fencing token | Two workers on the same resource at once |
| `FenceGate` / `fenced_update` | Stale lock holder overwriting newer state after TTL expiry |

Extracted from [ChessMate](https://chess-mate.online) (Celery + Redis + Postgres).
See [DESIGN.md](DESIGN.md) for guarantees, non-guarantees, and crash semantics.

## Install

```bash
pip install fencekit
pip install "fencekit[django]"   # optional Django QuerySet helper
```

Requires Redis 6+ (tested with Redis 7) and Python 3.10+.

## Quick example

```python
from datetime import timedelta
from redis import Redis

from fencekit import (
    DistributedLock,
    FenceGate,
    IdempotencyGuard,
    IdempotencyResultMissing,
    fenced_update,
    idempotency_key,
)

r = Redis.from_url("redis://localhost:6379/0", decode_responses=True)
guard = IdempotencyGuard(r)
lock = DistributedLock(r)
fence = FenceGate(r)

def analyze_batch(job) -> dict | None:
    key = idempotency_key(
        {"game_ids": ["abc", "def"], "engine": "sf16"},
        namespace="analysis",
    )
    if not guard.try_begin(key, ttl=timedelta(hours=24)):
        try:
            return guard.get_result(key)  # prior outcome on redelivery
        except IdempotencyResultMissing:
            return None  # still pending or done without a memo

    handle = lock.acquire(f"analysis:{job.pk}", ttl=timedelta(minutes=5))
    try:
        fence.set_if_fresh(handle.token, f"analysis:{job.pk}:status", "running")
        fenced_update(
            type(job).objects.filter(pk=job.pk),
            handle.token,
            updates={"progress": 50, "status": "running"},
        )
        result = {"report_id": job.pk, "status": "done"}
        guard.mark_done(key, result=result, ttl=timedelta(hours=24))
        return result
    finally:
        lock.release(handle)
```

## API overview

`idempotency_key(payload, namespace=...)`: deterministic key from JSON-canonicalized payload.

`IdempotencyGuard.try_begin` / `mark_done` / `get_result`: at-most-once start; optional JSON memo on completion.

`DistributedLock.acquire` / `release` / `extend`: lease plus monotonic fencing token (Lua).

`FenceGate.set_if_fresh`: atomic fenced Redis string writes.

`fenced_update(queryset, token, updates=...)`: fenced Django/Postgres `UPDATE` in one statement.

Typed public API (`py.typed`). No Celery adapter yet; wire the guard in your task body for now.

## Comparison

Short view. Sources and nuance: [docs/COMPARISON.md](docs/COMPARISON.md).

| | Dedup start | Celery plugin | Stale-write fencing | Postgres helper |
|---|:---:|:---:|:---:|:---:|
| fencekit | Yes | Manual | Yes | `fenced_update` |
| celery-once / celery-singleton | Yes | Yes | No | No |
| redis-py `Lock` | No | No | No | No |
| relier | Yes | Yes | Partial (framework) | App-owned |

fencekit complements celery-once. celery-once dedupes scheduling; fencekit rejects
writes from a worker whose lock TTL already expired.

## Local demo (no cloud)

Redis via Docker on your machine. No hosted services, no monthly bill.

```bash
docker compose -f examples/reference/docker-compose.yml up -d
pip install -e .
python examples/reference/demo_stale_fence.py
python examples/reference/demo_idempotency.py
```

See [examples/reference/README.md](examples/reference/README.md).

## Guarantees

| Claim | Status |
|-------|--------|
| At-most-once *start* within idempotency TTL | Yes (`SET NX`) |
| Memoized result after `mark_done(..., result=...)` | Yes (within TTL) |
| Mutual exclusion while lock TTL held (single Redis primary) | Best-effort lease |
| Stale holder blocked via `FenceGate` / `fenced_update` | Yes (when used) |
| Exactly-once delivery | No |
| Safety under Redis failover / split brain | No |
| Writes that skip the fencing token | No |

fencekit does not implement Redlock. Fencing only works when the storage layer
checks the token in the same operation as the write.

## Development

```bat
REM Windows (CMD)
python -m pip install -e ".[dev]"
python -m ruff check src tests
python -m mypy src
python -m pytest -m "not integration" -q
```

Full suite (Redis on `localhost:6379`):

```bat
set FENCEKIT_REDIS_URL=redis://localhost:6379/15
python -m pytest -q
```

```bash
# Linux/macOS with uv
uv sync --extra dev
uv run pytest
```

CI runs lint, type-check, and tests on Python 3.10–3.13 with Redis. Releases
publish to PyPI via [Trusted Publishing](RELEASING.md) (OIDC, no long-lived token).

## License

MIT
