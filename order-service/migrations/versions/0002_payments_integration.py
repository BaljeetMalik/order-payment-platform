"""payments integration: order payment statuses/columns, outbox, processed_events

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-09

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enum labels are OrderStatus member *names* (see 0001).
    for label in ("PAID", "PAYMENT_FAILED", "REFUNDED", "REFUND_FAILED"):
        op.execute(f"ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS '{label}'")

    op.execute("""
        ALTER TABLE orders
            ADD COLUMN payment_id           VARCHAR(32),
            ADD COLUMN payment_failure_code VARCHAR
    """)

    op.execute("""
        CREATE TABLE outbox (
            id           BIGSERIAL PRIMARY KEY,
            event_id     UUID NOT NULL UNIQUE,
            topic        VARCHAR NOT NULL,
            key          VARCHAR NOT NULL,
            payload      JSONB NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            published_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX ix_outbox_unpublished ON outbox (id) WHERE published_at IS NULL")

    op.execute("""
        CREATE TABLE processed_events (
            event_id     UUID PRIMARY KEY,
            processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS processed_events")
    op.execute("DROP TABLE IF EXISTS outbox")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS payment_failure_code, DROP COLUMN IF EXISTS payment_id")
    # Postgres cannot drop enum values; the extra orderstatus labels stay.