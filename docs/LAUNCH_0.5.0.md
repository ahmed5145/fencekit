# Launch notes: fencekit 0.5.0

Draft for LinkedIn or dev.to. Edit voice to taste before posting.

---

**Title idea:** fencekit 0.5.0: reclaim stale Celery jobs after a worker crash

**Hook:** Celery with `acks_late` is the right default. It also redelivers work when a worker dies. That is good until the same batch starts twice, or a stale holder overwrites progress after a lock TTL.

**What shipped in 0.5.0:**

- `try_begin_or_reclaim`: if a job key is stuck in `pending` and nobody holds the lock, a redelivery can take over instead of waiting for TTL
- `BeginOutcome` enum so callers know begun vs reclaimed vs done vs in progress
- Optional `fencekit.celery.idempotent_task` decorator

**What fencekit still does not claim:** exactly-once delivery, Redlock, HA mutual exclusion across Redis failover. Those limits are in DESIGN.md on purpose.

**Links to include:**

- PyPI: https://pypi.org/project/fencekit/
- DESIGN.md: https://github.com/ahmed5145/fencekit/blob/main/DESIGN.md
- Comparison: https://github.com/ahmed5145/fencekit/blob/main/docs/COMPARISON.md

**Closing line idea:** Extracted from ChessMate's Stockfish pipelines. Property-tested crash semantics, PyPI Trusted Publishing, MIT license.

---

## dev.to tags (suggested)

`python` `celery` `redis` `opensource` `pypi`

## LinkedIn checklist

- [ ] Link PyPI + GitHub in first comment if not in post body
- [ ] Mention fencing tokens in one sentence (differentiator vs celery-once)
- [ ] No "exactly-once" language
