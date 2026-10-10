# payment-service

FastAPI payment service backed by Postgres and a mocked third-party payment provider.

## Run

```sh
uv run main.py            # http://127.0.0.1:8001, docs at /docs
uv run pytest             # tests (in-memory + Postgres; Postgres runs skip if <db>_test is unreachable)
```

Env vars: `HOST`, `PORT`, `RELOAD=true`, `MOCK_GATEWAY_LATENCY_SECONDS` (simulated provider latency),
`DATABASE_URL` (Postgres, read from `.env`), `RUN_MIGRATIONS` (default `true`).

## Database

SQL migrations live in `migrations/versions/` (Alembic, raw SQL) and are applied
automatically on startup (`alembic upgrade head`). Run them manually with
`uv run alembic upgrade head`. Tables: `payments`, `refunds`, `idempotency_keys`.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET  | `/health` | Liveness check |
| POST | `/payments` | Create a payment (authorize, and capture unless `capture: false`). Supports `Idempotency-Key` header |
| GET  | `/payments` | List payments — filters: `customer_id`, `status`; paging: `limit`, `offset` |
| GET  | `/payments/{id}` | Get a payment |
| POST | `/payments/{id}/capture` | Capture an authorized payment (optional partial `amount`) |
| POST | `/payments/{id}/cancel` | Void an authorized payment |
| POST | `/payments/{id}/refunds` | Refund (optional partial `amount`, `reason`) |
| GET  | `/payments/{id}/refunds` | List refunds for a payment |

Amounts are integers in minor units (cents). Status flow:
`authorized → succeeded → partially_refunded → refunded`, `authorized → canceled`, or `failed` on decline.

Errors: `{"error": "<code>", "message": "..."}` with 402 (declined), 404, 409 (invalid state), 422 (validation / amount / idempotency key reuse), 502 (provider unavailable).

## Mock provider

`app/gateway.py` defines the `PaymentGateway` protocol and `MockPaymentGateway`. Outcomes are driven by the `payment_method` token:

| Token | Result |
|---|---|
| `pm_card_visa` (or any other) | Success |
| `pm_card_declined` | 402 `card_declined` |
| `pm_card_insufficient_funds` | 402 `insufficient_funds` |
| `pm_card_expired` | 402 `expired_card` |
| `pm_card_incorrect_cvc` | 402 `incorrect_cvc` |
| `pm_card_processing_error` | 502, nothing persisted (safe to retry) |
| `pm_card_refund_fail` | Payment succeeds, refunds fail with 402 `refund_failed` |

To use a real provider, implement `PaymentGateway` and pass it to `create_app(gateway=...)`.

Storage is Postgres via SQLAlchemy (`PostgresRepository` in `app/repository.py`, ORM mappings in
`app/db/tables.py`). `InMemoryRepository` is kept for tests. Tests use a separate `<db>_test`
database (override with `TEST_DATABASE_URL`).
