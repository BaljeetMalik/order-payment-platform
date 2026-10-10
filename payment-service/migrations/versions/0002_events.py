"""event integration: outbox, processed_events

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