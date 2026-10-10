from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from decimal import Decimal
from fastapi import HTTPException
from fastapi import status
from app.config import settings
from app.repositories.order_repository import OrderRepository
from app.models.order import Order, OrderItem
from app.schemas import OrderCreate, OrderStatus, OrderUpdate
from app.events.outbox import add_event
from app.events.schemas import ORDER_CANCELLED, ORDER_CREATED, ORDERS_TOPIC, Event

CANCELLABLE = {OrderStatus.PENDING, OrderStatus.PAID, OrderStatus.PAYMENT_FAILED} 
EDITABLE = {OrderStatus.PENDING, OrderStatus.PAID}
DELETABLE = {OrderStatus.PENDING, OrderStatus.CANCELED, OrderStatus.REFUNDED}

def to_cents(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1")))

class OrderService:
    def __init__(self, db: Session):
        self.db = db
        self.order_repository = OrderRepository(db)

    def create_order(self, order_data: OrderCreate) -> Order:

        items = [
            OrderItem(product_id=item.product_id, quantity=item.quantity, unit_price=item.unit_price)
            for item in order_data.items
        ]
        order = Order(
            user_id=order_data.user_id,
            total_price=sum((i.unit_price * i.quantity for i in items), Decimal("0.00")),
            shipping_address=order_data.shipping_address,
            status=order_data.status,
            items=items,
            )

        try:
            self.db.add(order)
            self.db.flush()
            add_event(self.db, ORDERS_TOPIC, Event(
                event_type=ORDER_CREATED, 
                order_id=order.id,
                payload={
                    "user_id": order.user_id,
                    "amount": to_cents(order.total_price),
                    "currency": settings.DEFAULT_CURRENCY,
                    "payment_method": order.payment_method,
                    "description": f"Order {order.id} created"
                }
            ))  # Closing add_event call
            self.db.commit()
        except IntegrityError as e:
            self.db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        except SQLAlchemyError as e:
            self.db.rollback()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

        return self.order_repository.get_order_by_id(order.id)
            
    def get_order_by_id(self, order_id: int) -> Order | None:
        return self.order_repository.get_order_by_id(order_id)

    def get_all_orders(self, skip: int = 0, limit: int | None = 100) -> list[Order]:
        return self.order_repository.get_all_orders(skip=skip, limit=limit)

    def update_order(self, order_id: int, order_data: OrderUpdate) -> Order:
        order = self._get_for_update(order_id)
        self._require(order, EDITABLE, "update")
        order.shipping_address = order_data.shipping_address
        self.db.commit()
        return self.order_repository.get_order_by_id(order_id)

    def cancel_order(self, order_id: int, reason: str = "canceled by customer") -> Order:
        order = self._get_for_update(order_id)
        self._require(order, CANCELLABLE, "cancel")
        order.status = OrderStatus.CANCELED
        # Always tell payment-service: it refunds if a payment exists, otherwise ignores it.
        add_event(self.db, ORDERS_TOPIC, Event(
            event_type=ORDER_CANCELLED, order_id=order.id, payload={"reason": reason},
        ))
        self.db.commit()
        return self.order_repository.get_order_by_id(order_id)

    def complete_order(self, order_id: int) -> Order:
        order = self._get_for_update(order_id)
        self._require(order, {OrderStatus.PAID}, "complete")
        order.status = OrderStatus.COMPLETED
        self.db.commit()
        return self.order_repository.get_order_by_id(order_id)

    def delete_order(self, order_id: int) -> None:
        order = self._get_for_update(order_id)
        self._require(order, DELETABLE, "delete")
        self.order_repository.delete_order(order)

    
# ---- helpers ----

    def _get_for_update(self, order_id: int) -> Order:
        order = self.db.get(Order, order_id, with_for_update=True)
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        return order

    def _require(self, order: Order, allowed: set[OrderStatus], action: str) -> None:
        if order.status not in allowed:
            self.db.rollback()  # release the row lock
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot {action} an order in status '{order.status.value}'",
            )
