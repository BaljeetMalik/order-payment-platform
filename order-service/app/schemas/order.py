from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

class OrderStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    PAYMENT_FAILED = "payment_failed"
    COMPLETED = "completed"
    CANCELED = "canceled"
    REFUNDED = "refunded"
    REFUND_FAILED = "refund_failed"

class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int
    unit_price: Decimal
    model_config = ConfigDict(extra="ignore")

class OrderCreate(BaseModel):
    user_id: int
    status: OrderStatus = OrderStatus.PENDING
    shipping_address: str
    payment_method: str = Field(min_length=1, description="The payment method used for the order")
    items: list[OrderItemCreate] = Field(...,min_length=1,max_length=100)
    model_config = ConfigDict(extra="ignore")

class OrderUpdate(BaseModel):
    shipping_address: str
    model_config = ConfigDict(extra="ignore")

class OrderItemResponse(BaseModel):
    order_id: int
    product_id: int
    unit_price: Decimal
    quantity: int
    model_config = ConfigDict(extra="ignore", from_attributes=True)

class OrderResponse(BaseModel):
    id: int
    user_id: int
    total_price: Decimal
    status: OrderStatus
    shipping_address: str
    payment_id: str | None = None
    payment_failure_code: str | None = None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse]
    model_config = ConfigDict(extra="ignore", from_attributes=True)
   
class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    model_config = ConfigDict(extra="ignore")
    


