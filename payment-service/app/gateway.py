"""Third-party payment provider interface and an in-process mock implementation.

The service only talks to providers through `PaymentGateway`, so swapping the
mock for a real client (Stripe, Adyen, ...) means implementing this protocol.
"""

import time
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4


class GatewayError(Exception):
    """Provider unreachable or returned a 5xx — outcome unknown, safe to retry."""


@dataclass(frozen=True)
class GatewayResult:
    success: bool
    provider_id: str | None = None
    decline_code: str | None = None
    message: str | None = None


class PaymentGateway(Protocol):
    def authorize(self, amount: int, currency: str, payment_method: str) -> GatewayResult: ...

    def capture(self, provider_payment_id: str, amount: int) -> GatewayResult: ...

    def void(self, provider_payment_id: str) -> GatewayResult: ...

    def refund(self, provider_payment_id: str, amount: int) -> GatewayResult: ...


# Test payment-method tokens recognised by the mock, modelled on Stripe's test cards.
_DECLINES: dict[str, tuple[str, str]] = {
    "pm_card_declined": ("card_declined", "The card was declined."),
    "pm_card_insufficient_funds": ("insufficient_funds", "The card has insufficient funds."),
    "pm_card_expired": ("expired_card", "The card has expired."),
    "pm_card_incorrect_cvc": ("incorrect_cvc", "The card's security code is incorrect."),
}
_ERROR_TOKEN = "pm_card_processing_error"
_REFUND_FAIL_TOKEN = "pm_card_refund_fail"


class MockPaymentGateway:
    """Deterministic fake provider.

    Behaviour is driven by the payment-method token:
      * any token in `_DECLINES`          -> authorization declined
      * `pm_card_processing_error`        -> GatewayError (simulated 5xx/timeout)
      * `pm_card_refund_fail`             -> authorizes fine, refunds are rejected
      * anything else (e.g. pm_card_visa) -> success
    """

    def __init__(self, latency_seconds: float = 0.0) -> None:
        self.latency_seconds = latency_seconds
        # provider_payment_id -> payment_method, so later calls can reproduce scenarios
        self._charges: dict[str, str] = {}
        self.calls: list[tuple[str, tuple]] = []

    def _simulate(self, op: str, *args) -> None:
        self.calls.append((op, args))
        if self.latency_seconds:
            time.sleep(self.latency_seconds)

    def authorize(self, amount: int, currency: str, payment_method: str) -> GatewayResult:
        self._simulate("authorize", amount, currency, payment_method)
        if payment_method == _ERROR_TOKEN:
            raise GatewayError("Payment provider is unavailable")
        if payment_method in _DECLINES:
            code, message = _DECLINES[payment_method]
            return GatewayResult(success=False, decline_code=code, message=message)
        provider_id = f"mock_ch_{uuid4().hex[:16]}"
        self._charges[provider_id] = payment_method
        return GatewayResult(success=True, provider_id=provider_id)

    def capture(self, provider_payment_id: str, amount: int) -> GatewayResult:
        self._simulate("capture", provider_payment_id, amount)
        if provider_payment_id not in self._charges:
            return GatewayResult(success=False, decline_code="resource_missing", message="Unknown charge")
        return GatewayResult(success=True, provider_id=provider_payment_id)

    def void(self, provider_payment_id: str) -> GatewayResult:
        self._simulate("void", provider_payment_id)
        if provider_payment_id not in self._charges:
            return GatewayResult(success=False, decline_code="resource_missing", message="Unknown charge")
        return GatewayResult(success=True, provider_id=provider_payment_id)

    def refund(self, provider_payment_id: str, amount: int) -> GatewayResult:
        self._simulate("refund", provider_payment_id, amount)
        method = self._charges.get(provider_payment_id)
        if method is None:
            return GatewayResult(success=False, decline_code="resource_missing", message="Unknown charge")
        if method == _REFUND_FAIL_TOKEN:
            return GatewayResult(success=False, decline_code="refund_failed", message="The refund was rejected by the issuer.")
        return GatewayResult(success=True, provider_id=f"mock_re_{uuid4().hex[:16]}")
