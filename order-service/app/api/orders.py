from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.order import OrderCreate, OrderUpdate
from app.services import OrderService
from app.schemas import OrderResponse

router = APIRouter(
    prefix="/orders",
    tags=["orders"]
)

@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(order_data: OrderCreate, db: Session = Depends(get_db)) -> OrderResponse:
    """Creates the order as PENDING; payment happens asynchronously. Poll GET /orders/{id}."""
    order = OrderService(db).create_order(order_data)
    return OrderResponse.model_validate(order)

@router.get("/", response_model=list[OrderResponse])
def list_orders(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)) -> list[OrderResponse]:
    orders = OrderService(db).get_all_orders(skip=skip, limit=limit)
    return [OrderResponse.model_validate(order) for order in orders]

# Must be declared before "/{order_id}", otherwise "all" is matched as an order id.
@router.get("/all", response_model=list[OrderResponse])
def list_all_orders(db: Session = Depends(get_db)) -> list[OrderResponse]:
    orders = OrderService(db).get_all_orders(limit=None)
    return [OrderResponse.model_validate(order) for order in orders]

@router.get("/{order_id}", response_model=OrderResponse)
def get_order(order_id: int, db: Session = Depends(get_db)) -> OrderResponse:
    order = OrderService(db).get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return OrderResponse.model_validate(order)

@router.put("/{order_id}", response_model=OrderResponse)
def update_order(order_id: int, order_data: OrderUpdate, db: Session = Depends(get_db)) -> OrderResponse:
    order = OrderService(db).update_order(order_id, order_data)
    return OrderResponse.model_validate(order)

@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order(order_id: int, db: Session = Depends(get_db)) -> None:
    OrderService(db).delete_order(order_id)

@router.post("/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(order_id: int, db: Session = Depends(get_db)) -> OrderResponse:
    order = OrderService(db).cancel_order(order_id)
    return OrderResponse.model_validate(order)

@router.post("/{order_id}/complete", response_model=OrderResponse)
def complete_order(order_id: int, db: Session = Depends(get_db)) -> OrderResponse:
    order = OrderService(db).complete_order(order_id)
    return OrderResponse.model_validate(order)