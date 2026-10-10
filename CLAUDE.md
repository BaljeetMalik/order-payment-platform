# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Layout

Monorepo with two independent Python 3.13 / FastAPI services plus their GitOps deployment:

- `order-service/` — order API (port 8000). Publishes `orders.events`, consumes `payments.events`.
- `payment-service/` — payment API with a mocked provider (port 8001). Consumes `orders.events`, publishes `payments.events`.
- `platform-gitops/` — Kubernetes manifests that Argo CD (in a local kind cluster) syncs.
- `.github/workflows/` — one pipeline per service, path-filtered to that service's folder.

Each service is its own uv project (own `pyproject.toml`, `uv.lock`, `.venv`). Run all commands from inside the service directory.

## Commands

```sh
cd order-service      # or payment-service
uv sync               # install deps (CI uses: uv sync --locked)
uv run main.py        # run; env: HOST, PORT, RELOAD=true
uv run ruff check .   # lint (migrations/ excluded)
uv run pytest -q      # tests
uv run pytest tests/test_payments.py::test_name   # single test
uv run alembic upgrade head                       # migrations (also run automatically on startup)
```

- Both services need Postgres on `localhost:5432` and Kafka on `localhost:9092`. `DATABASE_URL` is read from each service's `.env`.
- Set `KAFKA_ENABLED=false` to run/test without Kafka (CI does this). `RUN_MIGRATIONS=false` skips startup migrations; order-service also has `SEED_SAMPLE_DATA` (inserts sample users/products/orders when the DB is empty).
- payment-service tests are parametrized over `InMemoryRepository` and `PostgresRepository`; Postgres cases run against `<db>_test` (override with `TEST_DATABASE_URL`) and are skipped if it's unreachable.

## Architecture: order/payment choreography saga

The services talk only via Kafka, using the same event envelope (`app/events/schemas.py`, duplicated in both services — keep them in sync): `event_id`, `event_type`, `version`, `occurred_at`, `order_id`, `payload`. Message key is the `order_id`.

Each service has an identical `app/events/` stack:
- **Transactional outbox** (`outbox.py`): events are written to an `outbox` table in the same DB transaction as the state change, never sent to Kafka directly.
- **Relay** (`relay.py`): background task polling unpublished outbox rows (`FOR UPDATE SKIP LOCKED`) and publishing with an idempotent producer.
- **Consumer** (`consumer.py`): manual offset commit; handler runs in a thread with 3 attempts + exponential backoff, then the message goes to `<topic>.dlq`. Unparseable messages go straight to the DLQ.
- **Inbox dedup**: a `processed_events` table keyed by `event_id` makes redelivery a no-op.
- `runtime.py` wires producer + relay + consumer into the FastAPI lifespan (`app/main.py`).

Flow:
1. `POST /orders` creates a `PENDING` order and an `OrderCreated` outbox event (amount in cents).
2. payment-service `handle_order_event` charges via `PaymentService.create_payment` with idempotency key `order-{order_id}` — so a crash before the outbox commit + Kafka redelivery replays the same payment instead of double-charging. Emits `PaymentSucceeded` / `PaymentFailed`. `ProviderUnavailable` is re-raised so the consumer retries/dead-letters; bad payloads become `PaymentFailed` rather than DLQ.
3. order-service `handle_payment_event` applies the transition (`_apply` in `app/events/handlers.py` is the state machine over `(order.status, event_type)`).
4. Cancelling an order always emits `OrderCancelled`; payment-service refunds if a payment exists (looked up via the idempotency key) and emits `PaymentRefunded` / `RefundFailed`, moving the order to `REFUNDED` / `REFUND_FAILED`.

Order status rules (allowed actions per status) live in `order-service/app/services/order_service.py` (`CANCELLABLE`, `EDITABLE`, `DELETABLE`). Order rows are locked with `SELECT ... FOR UPDATE` for every mutation.

### Service internals
- **order-service**: layered — `api/` (routers) → `services/` (business rules, raises `HTTPException`) → `repositories/` → `models/` (SQLAlchemy ORM) with Pydantic `schemas/`. Prices are `Decimal` in the DB, converted to integer cents in events.
- **payment-service**: `api.py` → `service.py` (`PaymentService`, domain errors subclassing `PaymentError` mapped to `{"error", "message"}` JSON responses in `main.py`) → `repository.py` (`Repository` protocol; Postgres + in-memory impls, ORM rows in `db/tables.py`) and `gateway.py` (`PaymentGateway` protocol; `MockPaymentGateway` outcomes are driven by the `payment_method` token, e.g. `pm_card_declined`, `pm_card_processing_error`, `pm_card_refund_fail` — see `payment-service/README.md`). `create_app(gateway=..., repository=...)` allows injection for tests. Amounts are integer minor units.
- Migrations are Alembic with raw SQL in `migrations/versions/`; add new ones with the next numeric prefix.

## CI/CD and deployment

Push to `main` touching `<service>/**` → ruff + pytest → multi-arch image `ghcr.io/baljeetmalik/<service>:sha-xxxxxxx` → CI runs `kustomize edit set image` and commits the tag bump to `platform-gitops/services/<service>/kustomization.yaml` → Argo CD auto-syncs. Expect bot commits (`deploy <service> sha-…`) on `main`; pull before pushing.

GitOps structure: `bootstrap/root.yaml` is an app-of-apps pointing at `apps/`. Sync waves: `infra` (wave 0: Postgres, Kafka, and a hook Job creating the four topics `orders.events`, `payments.events`, and their `.dlq` variants) before the services (wave 1). In-cluster, migrations run in a PreSync `*-migrate` Job and the Deployment sets `RUN_MIGRATIONS=false`. `DATABASE_URL` comes from a `<service>-env` Secret that is not stored in the repo. Everything deploys to the `order-platform` namespace.
