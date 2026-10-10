"""initial schema: users, products, orders, order_items

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
    # Enum labels are the OrderStatus member *names*: SQLAlchemy's Enum(OrderStatus)
    # persists names, not values.
    op.execute("CREATE TYPE orderstatus AS ENUM ('PENDING', 'COMPLETED', 'CANCELED')")

    op.execute("""
        CREATE TABLE users (
            id       SERIAL PRIMARY KEY,
            name     VARCHAR NOT NULL,
            email    VARCHAR NOT NULL UNIQUE,
            password VARCHAR NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE products (
            id          SERIAL PRIMARY KEY,
            name        VARCHAR NOT NULL,
            description TEXT,
            price       NUMERIC(10, 2) NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE orders (
            id               SERIAL PRIMARY KEY,
            user_id          INTEGER NOT NULL REFERENCES users (id),
            total_price      NUMERIC(10, 2) NOT NULL,
            status           orderstatus NOT NULL DEFAULT 'PENDING',
            shipping_address VARCHAR NOT NULL,
            created_at       TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
            updated_at       TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
        )
    """)
    op.execute("CREATE INDEX ix_orders_user_id ON orders (user_id)")

    op.execute("""
        CREATE TABLE order_items (
            id         SERIAL PRIMARY KEY,
            order_id   INTEGER NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products (id),
            unit_price NUMERIC(10, 2) NOT NULL,
            quantity   INTEGER NOT NULL CHECK (quantity > 0)
        )
    """)
    op.execute("CREATE INDEX ix_order_items_order_id ON order_items (order_id)")
    op.execute("CREATE INDEX ix_order_items_product_id ON order_items (product_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS order_items")
    op.execute("DROP TABLE IF EXISTS orders")
    op.execute("DROP TABLE IF EXISTS products")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TYPE IF EXISTS orderstatus")
