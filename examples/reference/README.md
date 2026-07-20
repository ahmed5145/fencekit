# Reference demo (local only)

Runs on your machine. Nothing deploys to the cloud. No monthly bill beyond Docker
on your PC (free locally).

## Prerequisites

Docker for the Redis container. Python 3.10+ with fencekit installed from the repo
root.

## Start Redis

From the repository root:

```bash
docker compose -f examples/reference/docker-compose.yml up -d
```

Windows CMD:

```bat
docker compose -f examples\reference\docker-compose.yml up -d
```

## Install fencekit (editable)

```bash
pip install -e .
```

## Run demos

Idempotency and memoized result on redelivery:

```bash
python examples/reference/demo_idempotency.py
```

Stale lock holder fenced out after TTL:

```bash
python examples/reference/demo_stale_fence.py
```

## Stop Redis

```bash
docker compose -f examples/reference/docker-compose.yml down
```

## Out of scope

Full Celery plus Django stack (Celery adapter is planned). Hosted demo (nothing to
pay monthly). ChessMate production wiring lives in the ChessMate repo.

API and guarantees: [root README](../../README.md), [DESIGN.md](../../DESIGN.md).
