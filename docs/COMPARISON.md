# Comparison: fencekit vs related tools

How fencekit relates to other Python tools for duplicate Celery work and shared
resource writes. Trade-offs included, including cases where fencekit is the wrong
pick.

Scope: everything here assumes a single Redis primary unless noted. None of these
tools give you exactly-once delivery end-to-end. fencekit does not implement
Redlock or claim HA mutual exclusion across failover.

Sources: each project's public docs, source, and issue trackers (July 2026).
Re-check before you ship.

## Summary table

| | Dedup / at-most-once start | Celery integration | Fencing stale writes | Postgres helper | Result memo | Guarantee docs |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| fencekit | Yes (`SET NX` + owner) | Yes (`idempotent_task`) | Yes | `fenced_update` | `get_result` | [DESIGN.md](../DESIGN.md) |
| celery-once | Yes (lock at queue time) | Yes (`QueueOnce`) | No | No | No | Minimal |
| celery-singleton | Yes (lock at queue time) | Yes (`Singleton`) | No | No | No | Minimal |
| celery-once-task | Yes (queue + running locks) | Yes (base task) | No | No | No | README only |
| redis-py `Lock` | No | No | No | No | No | Client docs |
| rhubarb | Concurrent exclusivity | Yes (`LockableTask`) | No | No | No | README (Redlock) |
| relier | Yes (broader lifecycle) | Yes (`@rl_task`) | Partial (in framework) | App-owned | Yes | Project README |
| DIY `SET NX` | If you build it | No | If you build it | If you build it | If you build it | Yours |

## Pick fencekit when

Celery (or similar) can redeliver the same logical job (`acks_late`, retries).
Workers can hold a lock past usefulness (GC pause, slow I/O, Stockfish). Durable
state in Postgres or Django must reject writes from a stale holder after the lease
expires.

Pick something else when you only need to stop duplicate queueing (celery-once,
celery-singleton). Pick relier if you want a full Celery reliability layer
(resurrection, DLQ, OTel). For multi-master lock consensus, look at etcd or
ZooKeeper; none of the rows above cover that.

## fencekit

Small library: idempotency guard, leased lock with a monotonic fencing token, Redis
fence gate, Django `fenced_update`. Pulled from a production Celery pipeline on
ChessMate.

What it adds: double-start dedup, mutual exclusion, and stale-write rejection are
separate APIs. Property and integration tests cover lock expiry and crash-style
races. [DESIGN.md](../DESIGN.md) lists non-guarantees (no Redlock, no exactly-once,
cooperative storage). `mark_done(..., result=...)` plus `get_result` let a
redelivery return a prior JSON outcome.

Limits: Postgres fencing needs a `fence_token` column and `fenced_update` (or
equivalent SQL). Reclaim only runs when the lock key is absent; an active holder
blocks takeover. Single Redis primary; failover can break lease or fence
monotonicity (documented).

## celery-once

Source: [cameronmaske/celery-once](https://github.com/cameronmaske/celery-once)
(PyPI: `celery-once`).

`QueueOnce` acquires a Redis lock when the task is queued (`apply_async`).
Duplicate schedules raise `AlreadyQueued` (or block). The lock clears on task
completion via Celery's `after_return`, with a configurable timeout fallback
(default 60 minutes).

Drop-in Celery integration. Cuts duplicate queueing and broker churn. Uses redis-py
lock under the hood.

No fencing tokens. A worker that held a lock, lost it to TTL, and woke up has no
token the database can check. The lock is tied to scheduling, not to arbitrary
durable writes. Celery retries do not re-enable the lock (documented). With
`unlock_before_run=True`, the lock releases before execution; storage still has no
stale-write protection. Reported edge cases: lock can remain if Redis errors during
`apply_async` ([#123](https://github.com/cameronmaske/celery-once/issues/123));
stale locks after worker crash in
[#103](https://github.com/cameronmaske/celery-once/issues/103).

celery-once stops two runs at once. fencekit handles the case where the lease
expired and the late writer must lose at the database.

## celery-singleton

Source: [steinitzu/celery-singleton](https://github.com/steinitzu/celery-singleton).

`Singleton` keeps one queued or running instance per task name and arguments
(Redis lock). Duplicate `delay()` returns the same `AsyncResult`.

Simple model; widely used (~300k PyPI downloads/month in 2026). Supports
`unique_on` for partial argument keys. Offers `clear_locks` on worker start (with
the usual multi-worker caveats).

No fencing tokens or storage-side stale rejection. `lock_expiry` can allow a second
instance while the first may still be running (documented in their README). No
result memo for redelivered Celery messages.

Same bucket as celery-once for this page: queue/running dedup, not stale-write
safety.

## celery-once-task

Source: PyPI `celery-once-task` (2026).

Separate queue lock (at `apply_async`) and running lock (at execution). Duplicate
calls are dropped or rejected.

Finer granularity than celery-once alone. Documented TTLs for both lock types. No
fencing tokens, Postgres helper, or documented crash/restart semantics beyond TTL
expiry. Smaller adoption; judge maturity for your own risk tolerance.

## redis-py `Lock`

Source: [redis-py Lock docs](https://redis.readthedocs.io/en/stable/lock.html).

`SET key token NX PX ttl` with owner-checked release and extend via Lua. The token
is a random UUID for ownership, not a monotonic fence.

Widely used client primitive. Owner-safe release and extend.

No idempotency key, no Celery awareness, no fencing token for storage. Docs leave
deadlock and multi-client correctness to the caller. A paused holder can outlive
TTL and write unless the storage layer rejects stale writers (Kleppmann's
[locking article](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)).

fencekit's lock increments a monotonic fence counter on acquire and pairs with
`FenceGate` / `fenced_update`. redis-py Lock is the lower-level primitive.

## rhubarb

Source: PyPI `rhubarb`, Celery `LockableTask` using Redlock.

Prevents concurrent runs of the same task via the Redlock algorithm. Opinionated
Celery plugin; focuses on worker death and lock TTL.

Redlock is still debated under clock or network partitions (Kleppmann's critique).
fencekit avoids Redlock. No storage fencing tokens or SQL helpers.

rhubarb targets exclusive execution. fencekit targets safe writes after lease loss.

## relier

Source: PyPI `relier`, Celery reliability layer.

`@rl_task` adds idempotency, resurrection, timeouts, graceful shutdown, DLQ,
OpenTelemetry, and related lifecycle pieces. Uses Redis Lua for
claim/in-flight/completed states; their README mentions lease and fence tokens.

Decorator ergonomics (`.push()`, ops hooks). Broader scope than fencekit: crash
recovery, not only dedup and fencing.

Heavier dependencies (OTel, pydantic-settings, etc.). You adopt relier's framework;
fencekit stays a small primitive library. Postgres fencing is still your schema
plus update statements unless relier ships a Django helper like `fenced_update`
(check their docs if you are comparing in depth).

relier is closer to a batteries-included Celery reliability stack. fencekit is
primitives plus an explicit DESIGN.md you compose yourself. Overlap on
idempotency; not mutually exclusive in theory.

## DIY `SET NX`

Teams hand-roll `SET idem_key NX EX`, maybe a lock key, and hope.

Easy to miss: owner checks on complete, atomic fence plus write, stable JSON keys,
stale holder after TTL, redelivery returning prior results. fencekit exists because
those bugs showed up in a real codebase.

## References

- Martin Kleppmann, [How to do distributed locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)
- Redis, [Distributed locks pattern](https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/)
- celery-once README and issues linked above
- celery-singleton README
- redis-py Lock documentation
