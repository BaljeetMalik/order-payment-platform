"""initial schema: payments, refunds, idempotency_keys

Revision ID: 0001
Revises:
Create Date: 2026-10-09

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Statuses are stored as the lowercase PaymentStatus / RefundStatus values.
    # Amounts are integers in minor units (cents), matching app.models.
    op.execute("""
        CREATE TABLE payments (
            id                  VARCHAR(32) PRIMARY KEY,
            amount              BIGINT NOT NULL CHECK (amount > 0),
            amount_captured     BIGINT NOT NULL DEFAULT 0 CHECK (amount_captured >= 0),
            amount_refunded     BIGINT NOT NULL DEFAULT 0 CHECK (amount_refunded >= 0),
            currency            CHAR(3) NOT NULL,
            status              VARCHAR(32) NOT NULL CHECK (status IN (
                                    'authorized', 'succeeded', 'failed', 'canceled',
                                    'partially_refunded', 'refunded')),
            payment_method      VARCHAR NOT NULL,
            customer_id         VARCHAR,
            description         VARCHAR(500),
            metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
            provider_payment_id VARCHAR,
            failure_code        VARCHAR,
            failure_message     TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (amount_captured <= amount),
            CHECK (amount_refunded <= amount_captured)
        )
    """)
    op.execute("CREATE INDEX ix_payments_customer_id ON payments (customer_id)")
    op.execute("CREATE INDEX ix_payments_status ON payments (status)")
    op.execute("CREATE INDEX ix_payments_created_at ON payments (created_at DESC)")

    op.execute("""
        CREATE TABLE refunds (
            id                 VARCHAR(32) PRIMARY KEY,
            payment_id         VARCHAR(32) NOT NULL REFERENCES payments (id),
            amount             BIGINT NOT NULL CHECK (amount > 0),
            currency           CHAR(3) NOT NULL,
            status             VARCHAR(32) NOT NULL CHECK (status IN ('succeeded', 'failed')),
            reason             VARCHAR(500),
            provider_refund_id VARCHAR,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_refunds_payment_id ON refunds (payment_id)")

    op.execute("""
        CREATE TABLE idempotency_keys (
            key         VARCHAR PRIMARY KEY,
            fingerprint VARCHAR(64) NOT NULL,
            payment_id  VARCHAR(32) NOT NULL REFERENCES payments (id),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS idempotency_keys")
    op.execute("DROP TABLE IF EXISTS refunds")
    op.execute("DROP TABLE IF EXISTS payments")
