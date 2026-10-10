from decimal import Decimal

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.order import Order, OrderItem, Product, User
from app.schemas.order import OrderStatus

SAMPLE_USERS = [
    {"name": "Alice Johnson", "email": "alice@example.com", "password": "sample-password"},
    {"name": "Bob Smith", "email": "bob@example.com", "password": "sample-password"},
    {"name": "Carol White", "email": "carol@example.com", "password": "sample-password"},
]

SAMPLE_PRODUCTS = [
    {"name": "Wireless Mouse", "description": "Ergonomic 2.4GHz wireless mouse", "price": Decimal("24.99")},
    {"name": "Mechanical Keyboard", "description": "Tenkeyless keyboard with brown switches", "price": Decimal("89.00")},
    {"name": "USB-C Hub", "description": "7-in-1 hub with HDMI and card reader", "price": Decimal("39.50")},
    {"name": "27\" Monitor", "description": "1440p IPS display", "price": Decimal("279.99")},
    {"name": "Laptop Stand", "description": "Adjustable aluminium stand", "price": Decimal("32.00")},
]

# (user email, status, shipping address, [(product name, quantity), ...])
SAMPLE_ORDERS = [
    ("alice@example.com", OrderStatus.COMPLETED, "12 Baker Street, London",
     [("Wireless Mouse", 1), ("Mechanical Keyboard", 1)]),
    ("alice@example.com", OrderStatus.PENDING, "12 Baker Street, London",
     [("USB-C Hub", 2)]),
    ("bob@example.com", OrderStatus.PENDING, "742 Evergreen Terrace, Springfield",
     [("27\" Monitor", 2), ("Laptop Stand", 1)]),
    ("carol@example.com", OrderStatus.CANCELED, "221 Pine Road, Portland",
     [("Laptop Stand", 1)]),
]


def _insert_sample_data(db: Session) -> None:
    users = {u["email"]: User(**u) for u in SAMPLE_USERS}
    products = {p["name"]: Product(**p) for p in SAMPLE_PRODUCTS}
    db.add_all([*users.values(), *products.values()])

    for email, order_status, address, lines in SAMPLE_ORDERS:
        items = [
            OrderItem(product=products[name], quantity=qty, unit_price=products[name].price)
            for name, qty in lines
        ]
        db.add(Order(
            user=users[email],
            status=order_status,
            shipping_address=address,
            total_price=sum((i.unit_price * i.quantity for i in items), Decimal("0.00")),
            items=items,
        ))

    db.commit()


def seed_sample_data() -> None:
    """Insert sample users, products and orders if the database has no users yet."""
    with SessionLocal() as db:
        if db.scalar(select(exists().select_from(User))):
            return
        _insert_sample_data(db)
