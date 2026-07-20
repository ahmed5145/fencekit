# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-07-20

### Added

- `FenceKitHooks` optional callbacks on `IdempotencyGuard`, `DistributedLock`, and
  `FenceGate` for logging, metrics, or tracing
- `fencekit.otel.otel_hooks()` factory (`pip install fencekit[otel]`)
- Architecture flow diagram in [DESIGN.md](DESIGN.md)
- Test count badge in README

## [0.5.0] - 2026-07-20

### Added

- `IdempotencyGuard.try_begin_or_reclaim`: take over a stale `pending` key when the
  lock is free (worker crash without `mark_done`)
- `BeginOutcome` enum for begin / reclaim / done / in-progress results
- `IdempotencyGuard.owner_id` and `DistributedLock.lock_key` for lock pairing
- Optional Celery decorator: `fencekit.celery.idempotent_task` (`pip install fencekit[celery]`)

## [0.4.0] - 2026-07-20

### Added

- [docs/COMPARISON.md](docs/COMPARISON.md): comparison vs celery-once,
  celery-singleton, redis-py Lock, rhubarb, relier, and DIY `SET NX`
- [docs/CASE_STUDY.md](docs/CASE_STUDY.md): portfolio case study draft
- [examples/reference/](examples/reference/): local Docker Redis demos (no cloud)

## [0.3.2] - 2026-07-20

### Added

- `py.typed` marker for type checkers
- Dependabot config for GitHub Actions
- README badges (CI, PyPI, Python, license) and clearer API overview

## [0.3.1] - 2026-07-17

### Changed

- Public package metadata: author email is personal Gmail; school email is
  listed as maintainer. GitHub no-reply address removed.

## [0.3.0] - 2026-07-17

### Added

- `IdempotencyGuard.mark_done(..., result=...)` stores a JSON memo atomically
  with the done marker (same TTL; `None` is a valid result)
- `IdempotencyGuard.get_result` to read the memo on redelivery
- `IdempotencyResultMissing` when no memo is available
- `dumps_json` / `loads_json` helpers sharing canonicalize rules

## [0.2.0] - 2026-07-17

### Added

- `fenced_update` for Django QuerySets / SQL rows: compare and advance
  `fence_token` in the same `UPDATE` as the mutation
- Optional `django` extra; Django ORM tests under `tests/unit/test_django_storage.py`

### Clarified

- Redis `FenceGate.set_if_fresh` only protects Redis string writes; durable
  app state (Postgres) must use `fenced_update` or an equivalent statement

## [0.1.0] - 2026-07-16

### Added

- `idempotency_key` with deterministic JSON canonicalization
- owner-bound `IdempotencyGuard` via Redis `SET NX EX`
- `DistributedLock` with atomic acquire + fencing token (Lua)
- `FenceGate` with atomic fenced Redis string writes
- Typed public API (`py.typed`), errors, and key helpers
- Unit, property (Hypothesis), and Redis integration tests
- `DESIGN.md` documenting guarantees, non-guarantees, and crash semantics
