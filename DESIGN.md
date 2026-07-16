# Design: fencekit

## Purpose

fencekit provides small Redis primitives so background workers can coordinate
attempts and prevent stale overwrites when tasks are delivered at-least-once
(e.g. Celery with late ack).

It is not a Celery replacement, not exactly-once messaging, and not Redlock.

## Origin

ChessMate batch analysis jobs (import → Stockfish → report) were redelivered after
worker crashes. Duplicate batches wasted CPU and made progress/state confusing.
This library extracts the coordination pattern: idempotency key + lease lock +
fencing token, with tests that encode crash/expiry races.

## Threat model

**Trusted:** Redis is trusted infrastructure in v0.1 (no authz inside the library;
use Redis ACLs/network policy at the ops layer). Callers are trusted not to forge
`owner_id` for locks they do not hold (owner IDs are random UUIDs per acquire).

**Untrusted / hostile:** concurrent workers, process kill mid-task, GC pauses
longer than lock TTL, network delay delivering stale writes, Celery redelivery.

**Out of scope:** malicious Redis admins, compromised workers that bypass the
API, Redis split-brain / multi-primary failover correctness.

## Algorithms

### Idempotency

```
SET {prefix}:idem:{namespace}:{sha256} "pending:{owner_id}" NX EX ttl
```

Only one caller begins. `mark_done` uses Lua to compare the guard owner before
setting `done` (with an optional TTL refresh), so a stale worker cannot complete
a key reclaimed by another worker after expiry.

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
`INCR` deliberately precedes `SET` because Redis scripts do not roll back earlier
writes after a runtime error. A corrupt or overflowing counter therefore cannot
leave a lock without a token. Failed attempts can consume a token only if the
final `SET` unexpectedly fails; gaps are safe because monotonicity, not
contiguity, is required.

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
`FenceGate.set_if_fresh` executes the max-token comparison, max update, and
target `SET` in one Lua script. Other Redis data types require an equivalent
application Lua script. External stores must compare the token in the same
transaction or statement as their mutation.

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

Inspired by Martin Kleppmann’s fencing-token argument
([How to do distributed locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)):
TTL locks alone cannot stop a paused holder; **the storage layer must reject
stale tokens**. Redis's
[distributed-lock documentation](https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/)
also motivates random owner values and compare-before-delete release; fencekit
uses that ownership rule but deliberately does not implement Redlock.

## Guarantees

| Claim | Status |
|-------|--------|
| At-most-once *start* within the idempotency TTL (Redis up) | Yes |
| Mutual exclusion while lease held (single primary) | Best-effort |
| Stale holder cannot mutate via atomic `set_if_fresh` | Yes |
| Exactly-once delivery | No |
| HA / failover / Redlock safety | No |
| Writes that skip the token | No |

“At-most-once side effects” additionally requires the application storage layer
to combine the fencing check with a unique business-operation key in one
transaction. A fence prevents stale overwrites; it cannot make a non-idempotent
external API (for example, charging a card) exactly once.

## Non-guarantees and risks

1. **Not Redlock.** Multi-key majority locking is out of scope and controversial
   for correctness without fencing.
2. **Single Redis primary.** Asynchronous failover may allow overlapping leases
   or roll back a fence counter, so do not claim HA mutual exclusion or global
   token monotonicity across failover. Redis Cluster is unsupported in v0.1;
   multi-key Lua scripts also require keys in one hash slot.
3. **Clock skew.** Expiry uses Redis server `PX`, not client wall clocks, so
   worker-to-server skew does not decide ownership. A Redis server clock jump can
   still make leases expire early or late. Do not implement “lock valid until”
   on the worker wall clock; blocking waits use the client monotonic clock only.
4. **Cooperative storage.** Postgres (or S3, etc.) must also compare tokens in
   the mutation itself. A separate preflight check cannot protect another store.
5. **GC pause > TTL.** Expected; fencing is the mitigation, not infinite TTLs.
6. **Idempotency TTL.** Too short → duplicate begin after expiry; too long →
   stuck `pending` if a worker dies without `mark_done`/`clear`. Align with job
   SLA; v0.2 may add explicit takeover rules.
7. **Counter persistence and overflow.** Fence counters intentionally do not
   expire. Deleting/restoring/rolling them back can reuse old token values and
   breaks monotonicity. Redis integer overflow makes acquisition fail safely
   before the lock key is written.
8. **Ambiguous network outcomes.** A client timeout does not prove Redis did not
   apply a command. A fresh acquire cannot create a second lease while the first
   key remains, but the caller may not know it owns the first lease. Likewise,
   an idempotency `SET` whose reply was lost may suppress work until its TTL.
   Applications must treat connection errors as an unknown outcome and reconcile.

## Crash / restart semantics

1. **Kill while lock valid:** lock remains until TTL; redelivery fails acquire /
   `try_begin` while key is pending/done.
2. **Kill after TTL:** new owner gets higher token; stale atomic fenced writes
   fail (`FencedOutError`). See `tests/property/test_fencing_expiry.py`.
3. **Celery redelivery:** same idempotency key → `try_begin` is False while TTL
   holds.
4. **Partial side effects** (temp files, half-written rows) remain an application
   concern; fence every durable mutation.

## TTL guidance

- Lock TTL: longer than one chunk of work + heartbeat margin; extend regularly.
- Prefer short leases + extend over multi-hour locks (faster recovery after death).
- Idempotency TTL: at least the maximum job duration including retries; longer
  if duplicate begin after completion is unacceptable.

## Key naming

| Purpose | Pattern |
|---------|---------|
| Idempotency | `{prefix}:idem:{namespace}:{sha256}` |
| Lock | `{prefix}:lock:{resource}` |
| Fence sequence | `{prefix}:fence:seq:{resource}` |
| Fence max | `{prefix}:fence:max:{resource}` |

Default `prefix=fencekit`.

## Trust boundaries

- No pickle; payloads for keys are JSON-canonicalized by the caller.
- Redis URL/credentials are application secrets; the library does not log them.
- Treat Redis as trusted infra in v0.1; document ACL separation for production.

## Postgres pattern (app-owned)

```sql
UPDATE analysis_job
SET progress = %(progress)s, fence_token = %(token)s
WHERE id = %(id)s AND fence_token <= %(token)s;
-- rowcount 0 => fenced out
```

## Versioning

Semver from 0.1.0. Breaking API changes bump minor while 0.x.
