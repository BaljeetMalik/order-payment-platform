from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select
from app.models.order import Order 

class OrderRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_order(self, order: Order) -> Order:
        self.session.add(order)
        self.session.commit()
        self.session.refresh(order)
        return order

    def get_order_by_id(self, order_id: int) -> Order | None:
        return self.session.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
        ).scalar_one_or_none()

    def get_all_orders(self, skip: int = 0, limit: int | None = 100) -> list[Order]:
        """Return orders ordered by id; limit=None returns every order."""
        return self.session.execute(
            select(Order).options(selectinload(Order.items)).order_by(Order.id).offset(skip).limit(limit)
        ).scalars().all()

    def update_order(self, order: Order) -> Order:
        self.session.add(order)
        self.session.commit()
        self.session.refresh(order)
        return order
    
    def delete_order(self, order: Order) -> None:
        self.session.delete(order)
        self.session.commit()
        return None
    
        
    