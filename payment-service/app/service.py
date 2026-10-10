import hashlib
import json
import threading
from collections import defaultdict

from app.gateway import GatewayError, PaymentGateway
from app.models import (
    CapturePaymentRequest,
    CreatePaymentRequest,
    CreateRefundRequest,
    Payment,
    PaymentList,
    PaymentStatus,
    Refund,
    RefundStatus,
    utcnow,
)
from app.repository import Repository


class PaymentError(Exception):
    status_code = 400
    code = "payment_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFound(PaymentError):
    status_code = 404
    code = "not_found"


class InvalidState(PaymentError):
    status_code = 409
    code = "invalid_state"


class InvalidAmount(PaymentError):
    status_code = 422
    code = "invalid_amount"


class IdempotencyConflict(PaymentError):
    status_code = 422
    code = "idempotency_key_reused"


class Declined(PaymentError):
    """Provider rejected the operation. The resource is persisted with a failed status."""

    status_code = 402
    code = "declined"

    def __init__(self, message: str, *, code: str | None = None, resource_id: str | None = None) -> None:
        super().__init__(message, code=code)
        self.resource_id = resource_id


class ProviderUnavailable(PaymentError):
    status_code = 502
    code = "provider_unavailable"


class _KeyedLocks:
    """One lock per key, so operations on different payments don't block each other."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)

    def __call__(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks[key]


class PaymentService:
    def __init__(self, repo: Repository, gateway: PaymentGateway) -> None:
        self.repo = repo
        self.gateway = gateway
        self._payment_locks = _KeyedLocks()
        self._idem_locks = _KeyedLocks()

    # ---- Payments ----

    def create_payment(
        self, req: CreatePaymentRequest, idempotency_key: str | None = None
    ) -> tuple[Payment, bool]:
        """Returns (payment, replayed). `replayed` is True for an idempotent replay."""
        if idempotency_key is None:
            return self._create_payment(req), False

        fingerprint = hashlib.sha256(
            json.dumps(req.model_dump(), sort_keys=True).encode()
        ).hexdigest()
        with self._idem_locks(idempotency_key):
            existing = self.repo.get_idempotent(idempotency_key)
            if existing:
                stored_fingerprint, payment_id = existing
                if stored_fingerprint != fingerprint:
                    raise IdempotencyConflict(
                        "Idempotency-Key was already used with a different request body"
                    )
                return self._get(payment_id), True
            try:
                payment = self._create_payment(req)
            except Declined as exc:
                # A decline is a final outcome; replays should see the same failed payment.
                self.repo.put_idempotent(idempotency_key, fingerprint, exc.resource_id)
                raise
            self.repo.put_idempotent(idempotency_key, fingerprint, payment.id)
            return payment, False

    def _create_payment(self, req: CreatePaymentRequest) -> Payment:
        currency = req.currency.upper()
        try:
            auth = self.gateway.authorize(req.amount, currency, req.payment_method)
        except GatewayError as exc:
            # Nothing persisted: outcome unknown, client may retry with the same key.
            raise ProviderUnavailable(str(exc)) from exc

        payment = Payment(
            amount=req.amount,
            currency=currency,
            payment_method=req.payment_method,
            customer_id=req.customer_id,
            description=req.description,
            metadata=req.metadata,
            status=PaymentStatus.AUTHORIZED,
            provider_payment_id=auth.provider_id,
        )

        if not auth.success:
            payment.status = PaymentStatus.FAILED
            payment.failure_code = auth.decline_code
            payment.failure_message = auth.message
            self.repo.save_payment(payment)
            raise Declined(
                auth.message or "Payment declined", code=auth.decline_code, resource_id=payment.id
            )

        self.repo.save_payment(payment)
        if req.capture:
            return self.capture_payment(payment.id, CapturePaymentRequest())
        return payment

    def get_payment(self, payment_id: str) -> Payment:
        return self._get(payment_id)

    def list_payments(
        self,
        *,
        customer_id: str | None = None,
        status: PaymentStatus | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> PaymentList:
        items, total = self.repo.list_payments(
            customer_id=customer_id, status=status, limit=limit, offset=offset
        )
        return PaymentList(data=items, total=total, limit=limit, offset=offset)

    def capture_payment(self, payment_id: str, req: CapturePaymentRequest) -> Payment:
        with self._payment_locks(payment_id):
            payment = self._get(payment_id)
            if payment.status != PaymentStatus.AUTHORIZED:
                raise InvalidState(f"Cannot capture a payment in status '{payment.status}'")
            amount = req.amount if req.amount is not None else payment.amount
            if amount > payment.amount:
                raise InvalidAmount(
                    f"Capture amount {amount} exceeds authorized amount {payment.amount}"
                )

            result = self._call(self.gateway.capture, payment.provider_payment_id, amount)
            if not result.success:
                raise Declined(result.message or "Capture failed", code=result.decline_code)

            payment.amount_captured = amount
            payment.status = PaymentStatus.SUCCEEDED
            return self._touch(payment)

    def cancel_payment(self, payment_id: str) -> Payment:
        with self._payment_locks(payment_id):
            payment = self._get(payment_id)
            if payment.status != PaymentStatus.AUTHORIZED:
                raise InvalidState(f"Cannot cancel a payment in status '{payment.status}'")

            result = self._call(self.gateway.void, payment.provider_payment_id)
            if not result.success:
                raise Declined(result.message or "Cancel failed", code=result.decline_code)

            payment.status = PaymentStatus.CANCELED
            return self._touch(payment)

    # ---- Refunds ----

    def create_refund(self, payment_id: str, req: CreateRefundRequest) -> Refund:
        with self._payment_locks(payment_id):
            payment = self._get(payment_id)
            if payment.status not in (PaymentStatus.SUCCEEDED, PaymentStatus.PARTIALLY_REFUNDED):
                raise InvalidState(f"Cannot refund a payment in status '{payment.status}'")

            refundable = payment.amount_captured - payment.amount_refunded
            amount = req.amount if req.amount is not None else refundable
            if amount > refundable:
                raise InvalidAmount(f"Refund amount {amount} exceeds refundable amount {refundable}")

            result = self._call(self.gateway.refund, payment.provider_payment_id, amount)
            refund = Refund(
                payment_id=payment.id,
                amount=amount,
                currency=payment.currency,
                reason=req.reason,
                status=RefundStatus.SUCCEEDED if result.success else RefundStatus.FAILED,
                provider_refund_id=result.provider_id,
            )
            self.repo.add_refund(refund)
            if not result.success:
                raise Declined(
                    result.message or "Refund failed", code=result.decline_code, resource_id=refund.id
                )

            payment.amount_refunded += amount
            payment.status = (
                PaymentStatus.REFUNDED
                if payment.amount_refunded == payment.amount_captured
                else PaymentStatus.PARTIALLY_REFUNDED
            )
            self._touch(payment)
            return refund

    def list_refunds(self, payment_id: str) -> list[Refund]:
        self._get(payment_id)
        return self.repo.list_refunds(payment_id)

    # ---- Helpers ----

    def _get(self, payment_id: str) -> Payment:
        payment = self.repo.get_payment(payment_id)
        if payment is None:
            raise NotFound(f"Payment '{payment_id}' not found")
        return payment

    def _touch(self, payment: Payment) -> Payment:
        payment.updated_at = utcnow()
        self.repo.save_payment(payment)
        return payment

    @staticmethod
    def _call(fn, *args):
        try:
            return fn(*args)
        except GatewayError as exc:
            raise ProviderUnavailable(str(exc)) from exc
