# order-payment-platform

Monorepo for the order/payment saga and its deployment.

| Path | What |
|---|---|
| `order-service/` | FastAPI order API; publishes `orders.events`, consumes `payments.events` |
| `payment-service/` | FastAPI payment API (mock gateway); consumes `orders.events`, publishes `payments.events` |
| `platform-gitops/` | Kubernetes manifests that Argo CD deploys (Postgres, Kafka, both services) |
| `.github/workflows/` | One CI pipeline per service, triggered only by changes under that service's folder |

## CI/CD flow

push to `main` touching `order-service/**` → test → build `ghcr.io/baljeetmalik/order-service:sha-xxxxxxx`
→ CI commits the new tag to `platform-gitops/services/order-service/kustomization.yaml`
→ Argo CD (in the local kind cluster) syncs it.

## Run locally

```sh
cd order-service   && uv run main.py   # http://127.0.0.1:8000
cd payment-service && uv run main.py   # http://127.0.0.1:8001
```
Both need Postgres (`localhost:5432`) and Kafka (`localhost:9092`); see each service's README.
