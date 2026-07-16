# fencekit

Redis-backed primitives for **idempotent background jobs**: idempotency keys,
distributed locks, and **fencing tokens** so a stale lock holder cannot overwrite
state after losing the lock when the destination atomically enforces the token.

> Built for correctness under worker crash and Celery-style at-least-once
> redelivery — not for stars or download counts.

## Why

ChessMate ([chess-mate.online](https://chess-mate.online)) runs batch game-analysis
pipelines on Celery (import from Chess.com/Lichess → Stockfish → coaching report).
With Redis as broker/backend and late-ack reliability, a worker crash or redelivery
can re-run the same analysis job. Early on that meant duplicate work: the same game
batch progressing twice, wasted CPU, and confusing progress when two workers touched
the same job.

Celery’s docs are clear that late ack implies tasks must be idempotent — but “just
make it idempotent” is hand-wavy in application code. fencekit extracts the Redis
primitives needed (idempotency key + lock + fencing) into a small library with
property tests for crash/restart, so the guarantees are explicit and testable.

## Install

```bash
pip install fencekit
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
    idempotency_key,
)

r = Redis.from_url("redis://localhost:6379/0", decode_responses=True)
guard = IdempotencyGuard(r)
lock = DistributedLock(r)
fence = FenceGate(r)

def analyze_batch() -> None:
    key = idempotency_key(
        {"game_ids": ["abc", "def"], "engine": "sf16"},
        namespace="analysis",
    )
    if not guard.try_begin(key, ttl=timedelta(hours=24)):
        return  # already started or completed

    handle = lock.acquire("analysis:batch-42", ttl=timedelta(minutes=5))
    try:
        # Atomic fence check + Redis progress write:
        fence.set_if_fresh(handle.token, "analysis:batch-42:status", "running")
        # ... extend the lock on heartbeats and fence every durable write ...
        guard.mark_done(key)
    finally:
        lock.release(handle)
```

## Guarantees (honest)

| Claim | Status |
|-------|--------|
| At-most-once *start* within the idempotency TTL (Redis available) | Yes (`SET NX`) |
| Mutual exclusion while lock TTL held (single Redis primary) | Best-effort lease |
| Stale holder cannot overwrite via atomic `FenceGate.set_if_fresh` | Yes |
| Exactly-once delivery | **No** |
| Safety under Redis failover / split brain | **No** (v0.1) |
| Safety if the app writes without presenting the token | **No** |

See [DESIGN.md](DESIGN.md) for threat model, Lua algorithms, TTL guidance, and
crash/restart semantics. We do **not** implement Redlock.

Fencing prevents stale overwrites; it does not make an arbitrary external side
effect exactly once. For that, the destination must atomically enforce both the
fence token and a unique business-operation key.

## Interview artifact

Property test `tests/property/test_fencing_expiry.py`: worker abandons the lock
(simulated crash); after TTL a new owner gets token `N+1`; the stale token is
rejected by `FenceGate`.

## Running tests

```bat
REM CMD (Windows) — no uv required
cd /d C:\Users\hussah01\Projects\fencekit
python -m pip install -e ".[dev]"
python -m ruff check --fix src tests
python -m ruff check src tests
python -m mypy src
python -m pytest -m "not integration" -q
```

Full suite needs a Redis server on `localhost:6379` (Docker Desktop, Memurai, or WSL):

```bat
set FENCEKIT_REDIS_URL=redis://localhost:6379/15
python -m pytest -q
```

Integration tests skip cleanly when Redis is unreachable or `FENCEKIT_REDIS_URL` is unset.

```bash
# Linux/macOS with uv + Docker
uv sync --extra dev
uv run pytest -m "not integration"
docker run -d -p 6379:6379 --name fencekit-redis redis:7
export FENCEKIT_REDIS_URL=redis://localhost:6379/15
uv run pytest
```

## Status

v0.1.0 — publishable library focused on systems/correctness signal.

Resume line:

> Built fencekit, a Redis-backed library for idempotent background jobs with
> fencing tokens and distributed locks; property-tested crash/restart and
> lock-expiry races; typed public API and CI.

Celery adapters are intentionally out of scope for v0.1 (may arrive later as an
optional extra).

## License

MIT
