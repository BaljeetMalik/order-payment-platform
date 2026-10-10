from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"


class PaymentStatus(StrEnum):
    AUTHORIZED = "authorized"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"


class RefundStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# ---- Requests ----


class CreatePaymentRequest(BaseModel):
    amount: int = Field(gt=0, description="Amount in minor units (e.g. cents)")
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    payment_method: str = Field(
        min_length=1, description="Tokenized payment method, e.g. pm_card_visa"
    )
    customer_id: str | None = None
    description: str | None = Field(default=None, max_length=500)
    capture: bool = Field(
        default=True, description="Capture immediately; false = authorize only"
    )
    metadata: dict[str, str] = Field(default_factory=dict)


class CapturePaymentRequest(BaseModel):
    amount: int | None = Field(
        default=None, gt=0, description="Defaults to the full authorized amount"
    )


class CreateRefundRequest(BaseModel):
    amount: int | None = Field(
        default=None, gt=0, description="Defaults to the remaining refundable amount"
    )
    reason: str | None = Field(default=None, max_length=500)


# ---- Resources ----


class Refund(BaseModel):
    id: str = Field(default_factory=lambda: new_id("re"))
    payment_id: str
    amount: int
    currency: str
    status: RefundStatus
    reason: str | None = None
    provider_refund_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Payment(BaseModel):
    id: str = Field(default_factory=lambda: new_id("pay"))
    amount: int
    amount_captured: int = 0
    amount_refunded: int = 0
    currency: str
    status: PaymentStatus
    payment_method: str
    customer_id: str | None = None
    description: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    provider_payment_id: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class PaymentList(BaseModel):
    data: list[Payment]
    total: int
    limit: int
    offset: int


class ErrorResponse(BaseModel):
    error: str
    message: str

