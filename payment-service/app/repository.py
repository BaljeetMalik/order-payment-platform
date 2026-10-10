"""Storage backends. PostgresRepository is used by the app; InMemoryRepository backs fast unit tests."""

import threading
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.db.tables import IdempotencyKeyRow, PaymentRow, RefundRow
from app.models import Payment, PaymentStatus, Refund, RefundStatus


class Repository(Protocol):
    def save_payment(self, payment: Payment) -> None: ...

    def get_payment(self, payment_id: str) -> Payment | None: ...

    def list_payments(
        self,
        *,
        customer_id: str | None,
        status: PaymentStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Payment], int]: ...

    def add_refund(self, refund: Refund) -> None: ...

    def list_refunds(self, payment_id: str) -> list[Refund]: ...

    def get_idempotent(self, key: str) -> tuple[str, str] | None: ...

    def put_idempotent(self, key: str, fingerprint: str, payment_id: str) -> None: ...


class InMemoryRepository:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self._payments: dict[str, Payment] = {}
        self._refunds: dict[str, list[Refund]] = {}
        # (idempotency_key) -> (request fingerprint, payment_id)
        self._idempotency: dict[str, tuple[str, str]] = {}

    def save_payment(self, payment: Payment) -> None:
        with self.lock:
            self._payments[payment.id] = payment

    def get_payment(self, payment_id: str) -> Payment | None:
        return self._payments.get(payment_id)

    def list_payments(
        self,
        *,
        customer_id: str | None,
        status: PaymentStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Payment], int]:
        with self.lock:
            items = [
                p
                for p in self._payments.values()
                if (customer_id is None or p.customer_id == customer_id)
                and (status is None or p.status == status)
            ]
        items.sort(key=lambda p: p.created_at, reverse=True)
        return items[offset : offset + limit], len(items)

    def add_refund(self, refund: Refund) -> None:
        with self.lock:
            self._refunds.setdefault(refund.payment_id, []).append(refund)

    def list_refunds(self, payment_id: str) -> list[Refund]:
        return list(self._refunds.get(payment_id, []))

    def get_idempotent(self, key: str) -> tuple[str, str] | None:
        return self._idempotency.get(key)

    def put_idempotent(self, key: str, fingerprint: str, payment_id: str) -> None:
        with self.lock:
            self._idempotency[key] = (fingerprint, payment_id)


class PostgresRepository:
    """Each call runs in its own short-lived session and commits before returning."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    # ---- Payments ----

    def save_payment(self, payment: Payment) -> None:
        with self.session_factory() as session:
            session.merge(_payment_to_row(payment))
            session.commit()

    def get_payment(self, payment_id: str) -> Payment | None:
        with self.session_factory() as session:
            row = session.get(PaymentRow, payment_id)
            return _row_to_payment(row) if row else None

    def list_payments(
        self,
        *,
        customer_id: str | None,
        status: PaymentStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Payment], int]:
        filters = []
        if customer_id is not None:
            filters.append(PaymentRow.customer_id == customer_id)
        if status is not None:
            filters.append(PaymentRow.status == status.value)

        with self.session_factory() as session:
            total = session.scalar(select(func.count()).select_from(PaymentRow).where(*filters))
            rows = session.scalars(
                select(PaymentRow)
                .where(*filters)
                .order_by(PaymentRow.created_at.desc(), PaymentRow.id)
                .offset(offset)
                .limit(limit)
            ).all()
            return [_row_to_payment(r) for r in rows], total

    # ---- Refunds ----

    def add_refund(self, refund: Refund) -> None:
        with self.session_factory() as session:
            session.add(_refund_to_row(refund))
            session.commit()

    def list_refunds(self, payment_id: str) -> list[Refund]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(RefundRow)
                .where(RefundRow.payment_id == payment_id)
                .order_by(RefundRow.created_at, RefundRow.id)
            ).all()
            return [_row_to_refund(r) for r in rows]

    # ---- Idempotency ----

    def get_idempotent(self, key: str) -> tuple[str, str] | None:
        with self.session_factory() as session:
            row = session.get(IdempotencyKeyRow, key)
            return (row.fingerprint, row.payment_id) if row else None

    def put_idempotent(self, key: str, fingerprint: str, payment_id: str) -> None:
        stmt = insert(IdempotencyKeyRow).values(key=key, fingerprint=fingerprint, payment_id=payment_id)
        stmt = stmt.on_conflict_do_update(
            index_elements=[IdempotencyKeyRow.key],
            set_={"fingerprint": stmt.excluded.fingerprint, "payment_id": stmt.excluded.payment_id},
        )
        with self.session_factory() as session:
            session.execute(stmt)
            session.commit()


# ---- Row <-> model mapping ----


def _payment_to_row(p: Payment) -> PaymentRow:
    return PaymentRow(
        id=p.id,
        amount=p.amount,
        amount_captured=p.amount_captured,
        amount_refunded=p.amount_refunded,
        currency=p.currency,
        status=p.status.value,
        payment_method=p.payment_method,
        customer_id=p.customer_id,
        description=p.description,
        metadata_=dict(p.metadata),
        provider_payment_id=p.provider_payment_id,
        failure_code=p.failure_code,
        failure_message=p.failure_message,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _row_to_payment(r: PaymentRow) -> Payment:
    return Payment(
        id=r.id,
        amount=r.amount,
        amount_captured=r.amount_captured,
        amount_refunded=r.amount_refunded,
        currency=r.currency,
        status=PaymentStatus(r.status),
        payment_method=r.payment_method,
        customer_id=r.customer_id,
        description=r.description,
        metadata=r.metadata_,
        provider_payment_id=r.provider_payment_id,
        failure_code=r.failure_code,
        failure_message=r.failure_message,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _refund_to_row(r: Refund) -> RefundRow:
    return RefundRow(
        id=r.id,
        payment_id=r.payment_id,
        amount=r.amount,
        currency=r.currency,
        status=r.status.value,
        reason=r.reason,
        provider_refund_id=r.provider_refund_id,
        created_at=r.created_at,
    )


def _row_to_refund(r: RefundRow) -> Refund:
    return Refund(
        id=r.id,
        payment_id=r.payment_id,
        amount=r.amount,
        currency=r.currency,
        status=RefundStatus(r.status),
        reason=r.reason,
        provider_refund_id=r.provider_refund_id,
        created_at=r.created_at,
    )
