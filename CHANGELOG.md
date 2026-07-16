# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-16

### Added

- `idempotency_key` with deterministic JSON canonicalization
- owner-bound `IdempotencyGuard` via Redis `SET NX EX`
- `DistributedLock` with atomic acquire + fencing token (Lua)
- `FenceGate` with atomic fenced Redis string writes
- Typed public API (`py.typed`), errors, and key helpers
- Unit, property (Hypothesis), and Redis integration tests
- `DESIGN.md` documenting guarantees, non-guarantees, and crash semantics
