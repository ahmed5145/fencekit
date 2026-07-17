# fencekit

Redis-backed idempotency and fenced locks for background jobs. A destination that
atomically checks the fencing token can reject writes from a stale lock holder.

## Why

ChessMate ([chess-mate.online](https://chess-mate.online)) runs imported games
through Stockfish before writing a coaching report. With Redis as the Celery broker
and late acknowledgements enabled, a worker crash can cause the same job to be
delivered again. I saw batches progress twice. That wasted Stockfish CPU and left
the recorded progress ambiguous.

Celery requires late-ack tasks to be idempotent, but each task still needs code to
enforce that property. fencekit collects the Redis operations I used in ChessMate.
Its tests reproduce worker death and lock-expiry races.

## Install

```bash
pip install fencekit
# optional Django helper tests / apps that want the extra declared:
pip install "fencekit[django]"
# or
uv add fencekit
```

Requires Redis 6+ (tested with Redis 7) and Python 3.10+.

## 30-second example

```python
from datetime import timedelta
from redis import Redis

from fencekit import (
    DistributedLock,
    FenceGate,
    IdempotencyGuard,
    fenced_update,
    idempotency_key,
)

r = Redis.from_url("redis://localhost:6379/0", decode_responses=True)
guard = IdempotencyGuard(r)
lock = DistributedLock(r)
fence = FenceGate(r)

def analyze_batch(job) -> None:
    key = idempotency_key(
        {"game_ids": ["abc", "def"], "engine": "sf16"},
        namespace="analysis",
    )
    if not guard.try_begin(key, ttl=timedelta(hours=24)):
        return  # already started or completed

    handle = lock.acquire(f"analysis:{job.pk}", ttl=timedelta(minutes=5))
    try:
        # Redis progress (optional):
        fence.set_if_fresh(handle.token, f"analysis:{job.pk}:status", "running")
        # Durable Postgres / Django row (required for ChessMate-style state):
        fenced_update(
            type(job).objects.filter(pk=job.pk),
            handle.token,
            updates={"progress": 50, "status": "running"},
        )
        guard.mark_done(key)
    finally:
        lock.release(handle)
```

## Guarantees

| Claim | Status |
|-------|--------|
| At-most-once *start* within the idempotency TTL (Redis available) | Yes (`SET NX`) |
| Mutual exclusion while lock TTL held (single Redis primary) | Best-effort lease |
| Stale holder cannot overwrite via atomic `FenceGate.set_if_fresh` | Yes (Redis strings) |
| Stale holder cannot overwrite via `fenced_update` / equivalent SQL | Yes (when used) |
| Exactly-once delivery | No |
| Safety under Redis failover / split brain | No (v0.2) |
| Safety if the app writes without presenting the token | No |

See [DESIGN.md](DESIGN.md) for the threat model, Lua algorithms, TTL guidance, and
crash/restart semantics. fencekit does not implement Redlock.

Fencing covers stale overwrites only when the destination enforces the token in
the same operation as the write. Redis helpers do not protect Postgres rows;
use `fenced_update` (or the raw SQL pattern in DESIGN.md) for Django models.

## Running tests

```bat
REM CMD (Windows), no uv required
cd fencekit
python -m pip install -e ".[dev]"
python -m ruff check --fix src tests
python -m ruff check src tests
python -m mypy src
python -m pytest -m "not integration" -q
```

The full suite needs Redis on `localhost:6379`:

```bat
set FENCEKIT_REDIS_URL=redis://localhost:6379/15
python -m pytest -q
```

Integration tests skip cleanly when Redis is unreachable or `FENCEKIT_REDIS_URL` is unset.
Django ORM fencing tests run whenever Django is installed (`pip install -e ".[dev]"`
or `.[django]`).

```bash
# Linux/macOS with uv + Docker
uv sync --extra dev
uv run pytest -m "not integration"
docker run -d -p 6379:6379 --name fencekit-redis redis:7
export FENCEKIT_REDIS_URL=redis://localhost:6379/15
uv run pytest
```

v0.2 has no Celery adapter. A later release may add one as an optional extra.

## License

MIT
