# Case study: fencekit (portfolio draft)

Source material for a portfolio page. Update the ChessMate integration paragraph once
production wiring ships.

## Title

fencekit: fencing tokens for Celery jobs after worker crashes

## One-liner

Published Python library on PyPI. Stops duplicate background work and blocks stale
workers from corrupting shared state. Crash and expiry races are property-tested.

## Problem

[ChessMate](https://chess-mate.online) runs Stockfish inside Celery workers (Redis
broker, late acknowledgements). When a worker died mid-batch:

Celery redelivered the job. That is correct for reliability. A second worker could
start the same analysis again and burn Stockfish CPU. A paused worker could resume
after its lock TTL and overwrite progress a newer worker had already written.

Celery's docs say late-ack tasks must be idempotent. Redis gives `SET NX` and
locks. Storage-side fencing is still your job.

## Approach

Idempotency guard: at-most-once start per business key (`SET NX`).

Distributed lock with a monotonic token issued in the same Lua script as acquire.

Fence enforcement: reject writes when `token < max` (Redis Lua plus Django/Postgres
`fenced_update`).

[DESIGN.md](../DESIGN.md) lists what we do not guarantee: exactly-once, Redlock,
failover safety.

## What shipped

Lua scripts for atomic acquire, release, extend, and fenced writes. Hypothesis
property tests and Redis integration tests for lock expiry races.
`mark_done(..., result=...)` and `get_result` for redelivery with a memoized JSON
outcome. CI on Python 3.10 through 3.13. PyPI releases via Trusted Publishing
(OIDC).

## Comparison

[COMPARISON.md](COMPARISON.md) covers celery-once and celery-singleton. They dedupe
scheduling. They do not implement Kleppmann-style fencing at the database.

## Demo (local, $0)

```bash
docker compose -f examples/reference/docker-compose.yml up -d
pip install -e .
python examples/reference/demo_stale_fence.py
```

Redis runs in Docker on localhost. No cloud account.

## Links

- PyPI: https://pypi.org/project/fencekit/
- GitHub: https://github.com/ahmed5145/fencekit
- Design doc: [DESIGN.md](../DESIGN.md)

## Resume bullet (when ready)

Published fencekit to PyPI: Redis idempotency and fencing tokens with
Hypothesis-tested crash and expiry races; extracted from Celery analysis pipelines
on ChessMate; PyPI Trusted Publishing (OIDC).
