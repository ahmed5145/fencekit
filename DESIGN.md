# Design: fencekit

## Purpose

fencekit coordinates repeated delivery of background jobs and rejects stale
writes through Redis fencing tokens. Celery orchestration and Redlock are outside
its scope. The library makes no exactly-once delivery claim.

## Origin

ChessMate's Celery jobs analyze imported games with Stockfish and then write coaching
reports. Worker crashes caused some jobs to be delivered again. The same batch could
run twice. Duplicate runs wasted Stockfish CPU and left the saved progress ambiguous.
fencekit contains the Redis operations pulled from those tasks. Its tests reproduce
worker death and lock-expiry races.

## Threat model

Trusted: Redis is trusted infrastructure in v0.1 (no authz inside the library;
use Redis ACLs/network policy at the ops layer). Callers are trusted not to forge
`owner_id` for locks they do not hold (owner IDs are random UUIDs per acquire).

Untrusted / hostile: concurrent workers, process kill mid-task, GC pauses
longer than lock TTL, network delay delivering stale writes, Celery redelivery.

Redis administrators are outside the threat model. So are compromised workers that
bypass the API. The v0.1 model excludes split-brain and multi-primary failover.

## Algorithms

### Idempotency

```
SET {prefix}:idem:{namespace}:{sha256} "pending:{owner_id}" NX EX ttl
```

Only one caller begins. `mark_done` uses Lua to compare the guard owner before
setting `done` (with an optional TTL refresh), so a stale worker cannot complete
a key reclaimed by another worker after expiry.

When `mark_done(..., result=...)` is used, the same Lua script writes a companion
result key with the same TTL:

```
{prefix}:idem:{namespace}:{sha256}        -> "done"
{prefix}:idem:{namespace}:{sha256}:result -> canonical JSON
```

`None` is a valid memo (`null`). Completing without `result=` deletes any prior
memo. `get_result` raises `IdempotencyResultMissing` when the key is absent,
pending, done without a memo, or the memo expired. A successful `try_begin`
also deletes a leftover result key so a stale memo cannot outlive a reclaimed
idempotency entry.

`try_begin_or_reclaim` tries `try_begin` first, then atomically swaps
`pending:{old_owner}` to `pending:{new_owner}` when the companion lock key is
absent. If the lock key exists, another worker is active and the outcome is
`IN_PROGRESS`. Pair the same `lock_resource` string used in `DistributedLock.acquire`.

Canonicalization rules:

- top-level payload and nested objects are mappings with string keys;
- mapping keys are sorted recursively; sequence order is preserved;
- JSON uses compact separators, UTF-8 input, and `ensure_ascii=True`;
- integers and floats retain JSON's distinct spellings (`1` vs `1.0`);
- NaN/infinity, bytes, sets, datetimes, and custom objects are rejected;
- the key suffix is lowercase SHA-256 hex of the canonical JSON bytes; and
- namespaces are non-empty and contain neither whitespace nor `:`.

Callers must normalize business values (for example, datetime ISO format and
case normalization) before calling `idempotency_key`. Key stability is part of
the producer contract.

### Lock + fencing token (atomic)

Lua on acquire:

```lua
-- KEYS[1]=lock, KEYS[2]=sequence; ARGV[1]=owner, ARGV[2]=ttl_ms
if redis.call('EXISTS', KEYS[1]) == 1 then
  return false
end
local token = redis.call('INCR', KEYS[2])
if redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[2], 'NX') then
  return token
end
return false
```

The script is atomic: no other client can acquire between `EXISTS` and `SET`.
`INCR` precedes `SET` because Redis scripts do not roll back earlier
writes after a runtime error. A corrupt or overflowing counter therefore cannot
leave a lock without a token. Failed attempts can consume a token only if the
final `SET` unexpectedly fails. Gaps are safe; the counter only needs to increase.

Release and extend compare ownership in the same script as the mutation:

```lua
-- release: KEYS[1]=lock, ARGV[1]=owner
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0

-- extend: KEYS[1]=lock, ARGV[1]=owner, ARGV[2]=ttl_ms
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
```

This prevents a delayed owner from deleting or extending a replacement lease.

### Fence gate

```lua
local max = tonumber(redis.call('GET', max_key) or '0')
if tonumber(token) < max then return 0 end  -- stale
redis.call('SET', max_key, token)           -- equal token may rewrite
return 1
```

`check` and `check_and_advance` operate only on the token registry. They are
useful for diagnostics and coordination, but a check followed by a separate
write has a time-of-check/time-of-use race. For Redis string state,
`FenceGate.set_if_fresh` checks the token and writes the target in one Lua script.
The script also records the accepted token. Other Redis data types require an
equivalent application Lua script. External stores must compare the token in the
same transaction or statement as their mutation.

The Redis string helper is:

```lua
-- KEYS[1]=max_key, KEYS[2]=target; ARGV[1]=token, ARGV[2]=value
local max = tonumber(redis.call('GET', KEYS[1]) or '0')
local token = tonumber(ARGV[1])
if token < max then return 0 end
redis.call('SET', KEYS[1], ARGV[1])
redis.call('SET', KEYS[2], ARGV[2])
return 1
```

Martin Kleppmann describes the stale-holder problem in
[How to do distributed locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html).
TTL locks cannot stop a paused holder, so **the storage layer must reject stale
tokens**. Redis's
[distributed-lock documentation](https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/)
also motivates random owner values and compare-before-delete release. fencekit
uses that ownership rule and does not implement Redlock.

## Guarantees

| Claim | Status |
|-------|--------|
| At-most-once *start* within the idempotency TTL (Redis up) | Yes |
| Memoized JSON result after `mark_done(..., result=...)` | Yes (within TTL) |
| Mutual exclusion while lease held (single primary) | Best-effort |
| Stale holder cannot mutate via atomic `set_if_fresh` | Yes (Redis strings) |
| Stale holder cannot mutate via `fenced_update` / SQL | Yes (when used) |
| Exactly-once delivery | No |
| HA / failover / Redlock safety | No |
| Writes that skip the token | No |

At-most-once side effects require the application storage layer to combine the
fencing check with a unique business-operation key in one transaction. A fence
prevents stale overwrites. It cannot make a non-idempotent external API, such as
a card charge, execute exactly once.

## Non-guarantees and risks

1. Redlock. fencekit does not implement multi-key majority locking. Its v0.1
   safety model uses one Redis primary and storage-side fencing.
2. Single Redis primary. Asynchronous failover may allow overlapping leases
   or roll back a fence counter, so do not claim HA mutual exclusion or global
   token monotonicity across failover. Redis Cluster is unsupported in v0.1;
   multi-key Lua scripts also require keys in one hash slot.
3. Clock skew. Redis server `PX` controls expiry. Worker-to-server skew does not
   decide ownership. A Redis server clock jump can still make leases expire early
   or late. Do not implement "lock valid until" on the worker wall clock; blocking
   waits use the client monotonic clock only.
4. Cooperative storage. Postgres (or S3, etc.) must also compare tokens in
   the mutation itself. A separate preflight check cannot protect another store.
   For Django, use :func:`fencekit.storage.fenced_update` (or the SQL below).
5. GC pause > TTL. A newer token fences out the paused holder after its lease
   expires.
6. Idempotency TTL. Too short means a duplicate begin after expiry. Too long can
   leave a key stuck in `pending` if a worker dies without `mark_done`/`clear`.
   Align with the job SLA. Use `try_begin_or_reclaim` with the same lock resource
   to take over when the lock key is absent; while the lock is held, reclaim is
   refused (`BeginOutcome.IN_PROGRESS`).
7. Counter persistence and overflow. Fence counters intentionally do not
   expire. Deleting/restoring/rolling them back can reuse old token values and
   breaks monotonicity. Redis integer overflow makes acquisition fail safely
   before the lock key is written.
8. Ambiguous network outcomes. A client timeout does not prove Redis did not
   apply a command. A fresh acquire cannot create a second lease while the first
   key remains, but the caller may not know it owns the first lease. Likewise,
   an idempotency `SET` whose reply was lost may suppress work until its TTL.
   Applications must treat connection errors as an unknown outcome and reconcile.

## Crash / restart semantics

1. Kill while lock valid: lock remains until TTL; redelivery fails acquire /
   `try_begin` while key is pending/done.
2. Kill after TTL: new owner gets higher token; stale atomic fenced writes
   fail (`FencedOutError`). See `tests/property/test_fencing_expiry.py`.
3. Celery redelivery: same idempotency key means `try_begin` is False while TTL
   holds. If the first run stored a memo, `get_result` returns it. If the first
   worker died without `mark_done` and without holding the lock, call
   `try_begin_or_reclaim` to swap the pending owner. While the lock is held,
   outcome is `IN_PROGRESS`.
4. Partial side effects (temp files, half-written rows) remain an application
   concern; fence every durable mutation.

## TTL guidance

Set the lock TTL longer than one chunk of work plus its heartbeat margin. Extend
the lease regularly. Short leases recover faster after worker death than
multi-hour leases.

The idempotency TTL should cover retries and the maximum job duration. Use a longer
value when a duplicate start after completion would be unsafe.

## Key naming

| Purpose | Pattern |
|---------|---------|
| Idempotency | `{prefix}:idem:{namespace}:{sha256}` |
| Idempotency result | `{prefix}:idem:{namespace}:{sha256}:result` |
| Lock | `{prefix}:lock:{resource}` |
| Fence sequence | `{prefix}:fence:seq:{resource}` |
| Fence max | `{prefix}:fence:max:{resource}` |

Default `prefix=fencekit`.

## Trust boundaries

Payloads are JSON-canonicalized; fencekit does not use pickle. The library does
not log Redis URLs or credentials. v0.1 treats Redis as trusted infrastructure,
so production deployments should restrict it with network controls and Redis
ACLs.

## Postgres / Django pattern

Prefer the helper when using Django QuerySets:

```python
from fencekit import fenced_update

ok = fenced_update(
    AnalysisJob.objects.filter(pk=job_id),
    handle.token,
    updates={"progress": 50, "status": "running"},
)
# ok is False (or FencedOutError if raise_on_stale=True) when stale or missing
```

Equivalent SQL:

```sql
UPDATE analysis_job
SET progress = %(progress)s, fence_token = %(token)s
WHERE id = %(id)s AND fence_token <= %(token)s;
-- rowcount 0 => fenced out (or missing row)
```

Add a `fence_token` integer column (default `0`) on rows that durable workers
update under a lock. Redis `FenceGate` does not protect these rows by itself.

## Versioning

Semver from 0.1.0. Breaking API changes bump minor while 0.x. Additive helpers
such as `fenced_update` and result memoization are minor bumps.
