from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from app.models import (
    CapturePaymentRequest,
    CreatePaymentRequest,
    CreateRefundRequest,
    ErrorResponse,
    Payment,
    PaymentList,
    PaymentStatus,
    Refund,
)
from app.service import PaymentService

_errors = {
    code: {"model": ErrorResponse} for code in (402, 404, 409, 422, 502)
}

router = APIRouter(prefix="/payments", tags=["payments"], responses=_errors)


def get_service(request: Request) -> PaymentService:
    return request.app.state.payment_service


Service = Annotated[PaymentService, Depends(get_service)]


@router.post("", response_model=Payment, status_code=status.HTTP_201_CREATED)
def create_payment(
    body: CreatePaymentRequest,
    service: Service,
    response: Response,
    idempotency_key: Annotated[str | None, Header(max_length=255)] = None,
) -> Payment:
    payment, replayed = service.create_payment(body, idempotency_key)
    if replayed:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return payment


@router.get("", response_model=PaymentList)
def list_payments(
    service: Service,
    customer_id: str | None = None,
    status: PaymentStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaymentList:
    return service.list_payments(
        customer_id=customer_id, status=status, limit=limit, offset=offset
    )


@router.get("/{payment_id}", response_model=Payment)
def get_payment(payment_id: str, service: Service) -> Payment:
    return service.get_payment(payment_id)


@router.post("/{payment_id}/capture", response_model=Payment)
def capture_payment(
    payment_id: str, service: Service, body: CapturePaymentRequest | None = None
) -> Payment:
    return service.capture_payment(payment_id, body or CapturePaymentRequest())


@router.post("/{payment_id}/cancel", response_model=Payment)
def cancel_payment(payment_id: str, service: Service) -> Payment:
    return service.cancel_payment(payment_id)


@router.post(
    "/{payment_id}/refunds", response_model=Refund, status_code=status.HTTP_201_CREATED
)
def create_refund(
    payment_id: str, service: Service, body: CreateRefundRequest | None = None
) -> Refund:
    return service.create_refund(payment_id, body or CreateRefundRequest())


@router.get("/{payment_id}/refunds", response_model=list[Refund])
def list_refunds(payment_id: str, service: Service) -> list[Refund]:
    return service.list_refunds(payment_id)
