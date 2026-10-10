import pytest
from fastapi.testclient import TestClient

from app.gateway import MockPaymentGateway
from app.main import create_app


@pytest.fixture
def gateway() -> MockPaymentGateway:
    return MockPaymentGateway()


@pytest.fixture
def client(gateway: MockPaymentGateway, repository) -> TestClient:
    return TestClient(create_app(gateway, repository))


def make_payment(client: TestClient, **overrides) -> dict:
    body = {"amount": 1000, "currency": "usd", "payment_method": "pm_card_visa", **overrides}
    return client.post("/payments", json=body)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_payment_captures_by_default(client):
    resp = make_payment(client, customer_id="cus_1", metadata={"order": "42"})
    assert resp.status_code == 201
    p = resp.json()
    assert p["status"] == "succeeded"
    assert p["currency"] == "USD"
    assert p["amount_captured"] == 1000
    assert p["provider_payment_id"].startswith("mock_ch_")
    assert p["metadata"] == {"order": "42"}


def test_get_payment(client):
    pid = make_payment(client).json()["id"]
    resp = client.get(f"/payments/{pid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == pid


def test_get_missing_payment_404(client):
    resp = client.get("/payments/pay_nope")
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


@pytest.mark.parametrize(
    "body",
    [
        {"amount": 0, "currency": "USD", "payment_method": "pm_card_visa"},
        {"amount": 100, "currency": "US", "payment_method": "pm_card_visa"},
        {"amount": 100, "currency": "USD"},
    ],
)
def test_create_payment_validation(client, body):
    assert client.post("/payments", json=body).status_code == 422


@pytest.mark.parametrize(
    "method,code",
    [
        ("pm_card_declined", "card_declined"),
        ("pm_card_insufficient_funds", "insufficient_funds"),
        ("pm_card_expired", "expired_card"),
        ("pm_card_incorrect_cvc", "incorrect_cvc"),
    ],
)
def test_declined_payment_is_persisted_as_failed(client, method, code):
    resp = make_payment(client, payment_method=method)
    assert resp.status_code == 402
    err = resp.json()
    assert err["error"] == code
    p = client.get(f"/payments/{err['resource_id']}").json()
    assert p["status"] == "failed"
    assert p["failure_code"] == code


def test_provider_error_returns_502_and_persists_nothing(client):
    resp = make_payment(client, payment_method="pm_card_processing_error")
    assert resp.status_code == 502
    assert resp.json()["error"] == "provider_unavailable"
    assert client.get("/payments").json()["total"] == 0


def test_authorize_then_partial_capture(client):
    p = make_payment(client, capture=False).json()
    assert p["status"] == "authorized"
    assert p["amount_captured"] == 0

    resp = client.post(f"/payments/{p['id']}/capture", json={"amount": 600})
    assert resp.status_code == 200
    assert resp.json()["status"] == "succeeded"
    assert resp.json()["amount_captured"] == 600

    # Already captured
    assert client.post(f"/payments/{p['id']}/capture").status_code == 409


def test_capture_more_than_authorized(client):
    pid = make_payment(client, capture=False).json()["id"]
    resp = client.post(f"/payments/{pid}/capture", json={"amount": 5000})
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_amount"


def test_cancel_authorized_payment(client):
    pid = make_payment(client, capture=False).json()["id"]
    resp = client.post(f"/payments/{pid}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "canceled"
    assert client.post(f"/payments/{pid}/capture").status_code == 409


def test_cannot_cancel_captured_payment(client):
    pid = make_payment(client).json()["id"]
    assert client.post(f"/payments/{pid}/cancel").status_code == 409


def test_partial_then_full_refund(client):
    pid = make_payment(client).json()["id"]

    r1 = client.post(f"/payments/{pid}/refunds", json={"amount": 300, "reason": "damaged"})
    assert r1.status_code == 201
    assert r1.json()["status"] == "succeeded"
    assert client.get(f"/payments/{pid}").json()["status"] == "partially_refunded"

    # No amount -> refunds the remainder
    r2 = client.post(f"/payments/{pid}/refunds")
    assert r2.status_code == 201
    assert r2.json()["amount"] == 700

    p = client.get(f"/payments/{pid}").json()
    assert p["status"] == "refunded"
    assert p["amount_refunded"] == 1000

    refunds = client.get(f"/payments/{pid}/refunds").json()
    assert [r["amount"] for r in refunds] == [300, 700]

    assert client.post(f"/payments/{pid}/refunds").status_code == 409


def test_refund_exceeding_refundable(client):
    pid = make_payment(client).json()["id"]
    resp = client.post(f"/payments/{pid}/refunds", json={"amount": 1001})
    assert resp.status_code == 422


def test_cannot_refund_uncaptured_payment(client):
    pid = make_payment(client, capture=False).json()["id"]
    assert client.post(f"/payments/{pid}/refunds").status_code == 409


def test_failed_refund_is_recorded(client):
    pid = make_payment(client, payment_method="pm_card_refund_fail").json()["id"]
    resp = client.post(f"/payments/{pid}/refunds", json={"amount": 100})
    assert resp.status_code == 402
    assert resp.json()["error"] == "refund_failed"

    refunds = client.get(f"/payments/{pid}/refunds").json()
    assert len(refunds) == 1 and refunds[0]["status"] == "failed"
    p = client.get(f"/payments/{pid}").json()
    assert p["status"] == "succeeded" and p["amount_refunded"] == 0


def test_list_payments_filters_and_pagination(client):
    for _ in range(3):
        make_payment(client, customer_id="cus_a")
    make_payment(client, customer_id="cus_b", capture=False)

    assert client.get("/payments").json()["total"] == 4
    assert client.get("/payments", params={"customer_id": "cus_a"}).json()["total"] == 3
    assert client.get("/payments", params={"status": "authorized"}).json()["total"] == 1

    page = client.get("/payments", params={"limit": 2, "offset": 2}).json()
    assert len(page["data"]) == 2 and page["limit"] == 2 and page["offset"] == 2


def test_idempotent_create_replays_same_payment(client, gateway):
    headers = {"Idempotency-Key": "key-1"}
    body = {"amount": 500, "currency": "EUR", "payment_method": "pm_card_visa"}

    first = client.post("/payments", json=body, headers=headers)
    second = client.post("/payments", json=body, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.headers["Idempotent-Replayed"] == "true"
    assert first.json()["id"] == second.json()["id"]
    assert sum(1 for op, _ in gateway.calls if op == "authorize") == 1


def test_idempotency_key_reuse_with_different_body(client):
    headers = {"Idempotency-Key": "key-2"}
    client.post("/payments", json={"amount": 500, "currency": "EUR", "payment_method": "pm_card_visa"}, headers=headers)
    resp = client.post("/payments", json={"amount": 999, "currency": "EUR", "payment_method": "pm_card_visa"}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["error"] == "idempotency_key_reused"


def test_idempotent_replay_of_declined_payment(client):
    headers = {"Idempotency-Key": "key-3"}
    body = {"amount": 500, "currency": "EUR", "payment_method": "pm_card_declined"}
    first = client.post("/payments", json=body, headers=headers)
    second = client.post("/payments", json=body, headers=headers)
    assert first.status_code == 402
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["resource_id"]
    assert second.json()["status"] == "failed"
