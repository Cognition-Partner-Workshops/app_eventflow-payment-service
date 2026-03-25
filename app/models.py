"""Pydantic models for payment processing.

Monetary amounts arrive from the order service as integers in the smallest
currency unit (cents for USD, yen for JPY).  The payment processor converts
them to a ``float`` display amount for gateway validation.
"""

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class PaymentStatus(str, Enum):
    """Payment processing status."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class OrderItem(BaseModel):
    """A single item from the order event.

    Attributes:
        product_id: Product identifier.
        name: Human-readable product name.
        quantity: Number of units ordered.
        unit_price: Price per unit in the smallest currency unit.
    """

    product_id: str
    name: str
    quantity: int
    unit_price: int


class OrderCreatedEvent(BaseModel):
    """Inbound event consumed from the Azure Service Bus queue.

    This mirrors the ``OrderCreatedEvent`` schema published by the order
    service so both sides stay in sync.
    """

    event_id: str
    event_type: str
    timestamp: datetime
    data: "OrderEventData"


class OrderEventData(BaseModel):
    """Data payload of the OrderCreated event.

    Attributes:
        order_id: Unique identifier for the order.
        customer_id: Identifier of the customer who placed the order.
        currency: ISO 4217 currency code.
        amount: Total order amount in the smallest currency unit.
        items: Line items included in the order.
    """

    order_id: str
    customer_id: str
    currency: str
    amount: int
    items: list[OrderItem]


class PaymentRecord(BaseModel):
    """A processed payment record stored in the in-memory ledger.

    Attributes:
        payment_id: Auto-generated UUID for this payment.
        order_id: The order this payment corresponds to.
        customer_id: Customer who placed the order.
        currency: ISO 4217 currency code.
        amount_minor: Total in the smallest currency unit (e.g. cents).
        amount_display: Total converted to display format (e.g. dollars).
        status: Current processing status (pending, completed, failed).
        processed_at: UTC timestamp of when the payment was processed.
        error_message: Human-readable error detail when status is FAILED.
    """

    payment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    order_id: str
    customer_id: str
    currency: str
    amount_minor: int = Field(description="Amount in smallest currency unit")
    amount_display: float = Field(description="Amount in display format")
    status: PaymentStatus = PaymentStatus.PENDING
    processed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error_message: str | None = None
