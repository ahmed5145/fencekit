# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
