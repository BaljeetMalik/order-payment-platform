import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.events.schemas import (
    PAYMENT_FAILED,
    PAYMENT_SUCCEEDED,
    PAYMENT_REFUNDED,
    REFUND_FAILED,
    Event
)
from app.models.events import ProcessedEvent
from app.models.order import Order
from app.schemas.order import OrderStatus

log = logging.getLogger(__name__)

def handle_payment_event(session_factory: sessionmaker[Session], event: Event) -> None:
    with session_factory() as db:
        # Inbox: the PK on event_id makes redelivered events a no-op.
        db.add(ProcessedEvent(event_id=event.event_id))
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            log.info("duplicate %s event_id=%s ignored", event.event_type, event.event_id)
            return

        order = db.get(Order, event.order_id, with_for_update=True)
        if order is None:
            log.warning("%s for unknown order_id=%s", event.event_type, event.order_id)
            db.commit()
            return

        before = order.status
        _apply(order, event)
        db.commit()
        log.info("%s order_id=%s %s -> %s payment_id=%s", event.event_type, order.id,
                 before.value, order.status.value, order.payment_id)

def _apply(order: Order, event: Event) -> None:
    p = event.payload
    match (order.status, event.event_type):
        case (OrderStatus.PENDING, "PaymentSucceeded"):
            order.status = OrderStatus.PAID
            order.payment_id = p["payment_id"]
        case (OrderStatus.PENDING, "PaymentFailed"):
            order.status = OrderStatus.PAYMENT_FAILED
            order.payment_id = p.get("payment_id")
            order.payment_failure_code = p.get("failure_code")
        case (OrderStatus.CANCELED, "PaymentSucceeded"):
            # Canceled while the charge was in flight; payment-service will refund it next.
            order.payment_id = p["payment_id"]
        case (OrderStatus.CANCELED, "PaymentFailed"):
            order.payment_id = p.get("payment_id")
            order.payment_failure_code = p.get("failure_code")
        case (OrderStatus.CANCELED, "PaymentRefunded"):
            order.status = OrderStatus.REFUNDED
        case (OrderStatus.CANCELED, "RefundFailed"):
            order.status = OrderStatus.REFUND_FAILED
            order.payment_failure_code = p.get("failure_code")
        case _:
            log.warning("ignoring %s for order_id=%s in status %s",
                        event.event_type, order.id, order.status.value)


# Keeps the event-type constants referenced in one place for readers/grep.
HANDLED = {PAYMENT_SUCCEEDED, PAYMENT_FAILED, PAYMENT_REFUNDED, REFUND_FAILED}
        