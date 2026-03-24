"""Pydantic models for payment processing.

Defines the data structures used throughout the service:

- **Inbound events**: ``OrderCreatedEvent`` and ``OrderEventData`` represent the
  JSON messages consumed from Azure Service Bus.
- **Domain models**: ``PaymentStatus`` (enum) and ``PaymentRecord`` capture the
  outcome of payment processing.
- **Supporting models**: ``OrderItem`` describes a single line item within an order.
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
    """A single line item within an order event.

    Attributes:
        product_id: Unique product identifier.
        name: Human-readable product name.
        quantity: Number of units ordered.
        unit_price: Price per unit in the smallest currency denomination (e.g., cents).
    """

    product_id: str
    name: str
    quantity: int
    unit_price: int


class OrderCreatedEvent(BaseModel):
    """Top-level envelope for an ``OrderCreated`` event from the Order Service.

    Attributes:
        event_id: Unique identifier for this event instance.
        event_type: Event type discriminator (expected: ``OrderCreated``).
        timestamp: ISO-8601 timestamp of when the event was produced.
        data: Nested payload containing order details.
    """

    event_id: str
    event_type: str
    timestamp: datetime
    data: "OrderEventData"


class OrderEventData(BaseModel):
    """Data payload nested inside an ``OrderCreatedEvent``.

    Attributes:
        order_id: Unique identifier of the order.
        customer_id: Identifier of the customer who placed the order.
        currency: ISO 4217 currency code (e.g., ``USD``, ``JPY``).
        amount: Total order amount in the smallest currency unit (e.g., cents).
        items: List of line items included in the order.
    """

    order_id: str
    customer_id: str
    currency: str
    amount: int
    items: list[OrderItem]


class PaymentRecord(BaseModel):
    """A processed payment record stored in memory and served via the REST API.

    Attributes:
        payment_id: Auto-generated UUID for the payment.
        order_id: Identifier of the originating order.
        customer_id: Identifier of the customer.
        currency: ISO 4217 currency code.
        amount_minor: Amount in the smallest currency unit (as received).
        amount_display: Amount converted to display format (e.g., dollars).
        status: Processing outcome -- ``pending``, ``completed``, or ``failed``.
        processed_at: UTC timestamp of when the payment was processed.
        error_message: Human-readable error description if the payment failed.
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
