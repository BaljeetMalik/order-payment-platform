from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

ORDERS_TOPIC = "orders.events"
PAYMENTS_TOPIC = "payments.events"

#Event Type
ORDER_CREATED = "OrderCreated"
ORDER_CANCELLED = "OrderCancelled"
PAYMENT_SUCCEEDED = "PaymentSucceeded"
PAYMENT_FAILED = "PaymentFailed"
PAYMENT_REFUNDED = "PaymentRefunded"
REFUND_FAILED = "RefundFailed"

class Event(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    version: str = "1.0"
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    order_id: int
    payload: dict[str, Any] = Field(default_factory=dict)





