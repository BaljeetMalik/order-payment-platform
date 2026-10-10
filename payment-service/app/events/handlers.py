"""Turns order events into payment operations and emits the outcome as payment events."""

import logging

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.tables import ProcessedEvent
from app.events.outbox import add_event
from app.events.schemas import (
    ORDER_CANCELLED,
    ORDER_CREATED,
    PAYMENT_FAILED,
    PAYMENT_REFUNDED,
    PAYMENT_SUCCEEDED,
    PAYMENTS_TOPIC,
    REFUND_FAILED,
    Event,
)
from app.models import (
    CreatePaymentRequest,
    CreateRefundRequest,
    Payment,
    PaymentStatus,
    RefundStatus,
)
from app.service import Declined, InvalidState, PaymentService

log = logging.getLogger(__name__)


def idempotency_key(order_id: int) -> str:
    return f"order-{order_id}"

def handle_order_event(
    service: PaymentService, session_factory: sessionmaker[Session], event: Event
) -> None:
    with session_factory() as db:
        if db.get(ProcessedEvent, event.event_id):
            log.info("duplicate %s event_id=%s ignored", event.event_type, event.event_id)
            return

    # Payment work happens outside the DB transaction. If we crash before the commit below,
    # Kafka redelivers and the Idempotency-Key replays the same payment instead of charging twice.
    match event.event_type:
        case "OrderCreated":
            result = _charge(service, event)
        case "OrderCancelled":
            result = _refund(service, event)
        case _:
            log.warning("ignoring unknown event_type=%s", event.event_type)
            result = None

    with session_factory() as db:
        db.add(ProcessedEvent(event_id=event.event_id))
        if result is not None:
            add_event(db, PAYMENTS_TOPIC, result)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # processed concurrently by another consumer; its result was emitted
            return
    log.info("%s order_id=%s -> %s", event.event_type, event.order_id,
             result.event_type if result else "no-op")

def _charge(service: PaymentService, event: Event) -> Event:
    p = event.payload
    try:
        req = CreatePaymentRequest(
            amount=p.get("amount"),
            currency=p.get("currency"),
            payment_method=p.get("payment_method"),
            description=p.get("description"),
            customer_id=f"user_{p.get('user_id')}",
            metadata={"order_id": str(event.order_id)},
            capture=True,
        )
    except ValidationError as exc:
        # A bad payload won't fix itself on retry; fail the order instead of dead-lettering it.
        fields = ", ".join(".".join(map(str, e["loc"])) for e in exc.errors())
        log.warning("invalid OrderCreated order_id=%s: %s", event.order_id, fields)
        return _failed(event.order_id, None, "invalid_request", f"Invalid payment fields: {fields}")
    try:
        payment, _replayed = service.create_payment(req, idempotency_key(event.order_id))
    except Declined as exc:
        return _failed(event.order_id, exc.resource_id, exc.code, exc.message)
    # ProviderUnavailable propagates: the consumer retries, then dead-letters.

    if payment.status == PaymentStatus.FAILED:
        # Idempotent replay of an earlier decline returns the failed payment without raising.
        return _failed(event.order_id, payment.id, payment.failure_code, payment.failure_message)
    return _succeeded(event.order_id, payment)


def _refund(service: PaymentService, event: Event) -> Event | None:
    found = service.repo.get_idempotent(idempotency_key(event.order_id))
    if found is None:
        return None  # never charged
    _fingerprint, payment_id = found
    payment = service.get_payment(payment_id)

    if payment.status == PaymentStatus.REFUNDED:
        # Refunded already (e.g. crash before emitting); re-announce it.
        refunds = [r for r in service.list_refunds(payment_id) if r.status == RefundStatus.SUCCEEDED]
        last = refunds[-1] if refunds else None
        return Event(event_type=PAYMENT_REFUNDED, order_id=event.order_id, payload={
            "payment_id": payment_id,
            "refund_id": last.id if last else None,
            "amount": payment.amount_refunded,
        })
    if payment.status not in (PaymentStatus.SUCCEEDED, PaymentStatus.PARTIALLY_REFUNDED):
        return None  # failed / canceled: nothing to give back

    try:
        refund = service.create_refund(
            payment_id, CreateRefundRequest(reason=event.payload.get("reason") or "order canceled")
        )
    except Declined as exc:
        return Event(event_type=REFUND_FAILED, order_id=event.order_id, payload={
            "payment_id": payment_id,
            "refund_id": exc.resource_id,
            "failure_code": exc.code,
            "failure_message": exc.message,
        })
    except InvalidState:
        return None
    return Event(event_type=PAYMENT_REFUNDED, order_id=event.order_id, payload={
        "payment_id": payment_id, "refund_id": refund.id, "amount": refund.amount,
    })

def _succeeded(order_id: int, payment: Payment) -> Event:
    return Event(event_type=PAYMENT_SUCCEEDED, order_id=order_id, payload={
        "payment_id": payment.id, "amount": payment.amount, "currency": payment.currency,
    })


def _failed(order_id: int, payment_id: str | None, code: str | None, message: str | None) -> Event:
    return Event(event_type=PAYMENT_FAILED, order_id=order_id, payload={
        "payment_id": payment_id, "failure_code": code, "failure_message": message,
    })


HANDLED = {ORDER_CREATED, ORDER_CANCELLED}