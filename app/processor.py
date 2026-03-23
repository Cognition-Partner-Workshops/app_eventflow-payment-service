"""Payment processing logic.

This module converts order amounts from minor units (cents/smallest denomination)
to display amounts and validates the payment.

Pipeline:  convert_to_display_amount → validate_payment_amount
           → process_payment_through_gateway → PaymentRecord

BUG: The conversion assumes ALL currencies have 2 decimal places.
This works for USD, EUR, GBP but FAILS for zero-decimal currencies
like JPY and KRW where the amount is already in the base unit.

When a JPY order with amount=15800 arrives:
  - display_amount = 15800 / 100 = 158.00  (WRONG — should be 15800)
  - The consistency check compares display_amount * 100 back to the original
  - 158.00 * 100 = 15800 — this actually passes for amounts divisible by 100
  - BUT for amount=15850: 15850 / 100 = 158.50, 158.50 * 100 = 15850 — also passes
  - The REAL failure: the gateway validates display_amount against known price ranges
    for the currency, and 158.00 JPY is below the minimum transaction threshold
    (500 JPY), causing a validation error that is not caught → unhandled exception

The ValueError propagates through consumer._process_message, which abandons
the Service Bus message and attempts a best-effort HTTP callback to mark the
order as failed.
"""

import logging
from dataclasses import dataclass

from app.models import OrderEventData, PaymentRecord, PaymentStatus

logger = logging.getLogger(__name__)

# Minimum transaction thresholds in display currency units.
# Used by validate_payment_amount to reject unreasonably small charges.
# Currencies not listed here fall back to 0.50 (see validate_payment_amount).
MINIMUM_TRANSACTION_THRESHOLDS: dict[str, float] = {
    "USD": 0.50,
    "EUR": 0.50,
    "GBP": 0.30,
    "JPY": 500.0,
    "KRW": 500.0,
    "CHF": 0.50,
    "CAD": 0.50,
    "AUD": 0.50,
    "CNY": 3.00,
    "INR": 50.0,
}


@dataclass
class GatewayResponse:
    """Simulated payment gateway response."""

    success: bool
    transaction_id: str | None = None
    error: str | None = None


def convert_to_display_amount(amount_minor: int, currency: str) -> float:
    """Convert an amount from minor units to display format.

    Args:
        amount_minor: Amount in the smallest currency unit (e.g., cents).
        currency: ISO 4217 currency code.

    Returns:
        The amount in display format (e.g., dollars).

    BUG: Always divides by 100, which is incorrect for zero-decimal
    currencies like JPY where 1 yen IS the smallest unit.
    A correct implementation would use a per-currency exponent map
    (e.g. ISO 4217 defines JPY exponent as 0, USD as 2).
    """
    # BUG: This assumes all currencies have 2 decimal places.
    # For JPY 15800 this produces 158.00 instead of 15800,
    # which later fails the minimum threshold check (500 JPY).
    return amount_minor / 100


def validate_payment_amount(display_amount: float, currency: str) -> None:
    """Validate that the payment amount meets minimum thresholds.

    This is the function that actually surfaces the zero-decimal bug:
    the incorrectly converted display_amount (e.g. 158.00 JPY) is
    compared against the real-world threshold (500 JPY), raising a
    ValueError that propagates up to the consumer.

    Args:
        display_amount: Amount in display format.
        currency: ISO 4217 currency code.

    Raises:
        ValueError: If the amount is below the minimum threshold.
    """
    # Fall back to 0.50 for unlisted currencies (safe for most 2-decimal currencies).
    threshold = MINIMUM_TRANSACTION_THRESHOLDS.get(currency, 0.50)
    if display_amount < threshold:
        raise ValueError(
            f"Amount {display_amount} {currency} is below minimum threshold {threshold} {currency}"
        )


def process_payment_through_gateway(
    display_amount: float,
    currency: str,
    order_id: str,
) -> GatewayResponse:
    """Simulate processing a payment through an external gateway.

    In a real system this would call Stripe, Adyen, etc.
    For the demo, it validates the amount and returns a simulated response.

    Note: validate_payment_amount raises ValueError on failure rather than
    returning a GatewayResponse with success=False — callers must handle
    the exception (see consumer._process_message).

    Args:
        display_amount: Amount in display format.
        currency: ISO 4217 currency code.
        order_id: The order being paid for.

    Returns:
        A GatewayResponse indicating success or failure.
    """
    # Validate minimum amount — this is where the JPY bug manifests
    # JPY 15800 → display_amount = 158.00 → below 500 JPY threshold → CRASH
    validate_payment_amount(display_amount, currency)

    # Simulate successful gateway response
    import uuid

    return GatewayResponse(
        success=True,
        transaction_id=f"txn-{uuid.uuid4().hex[:12]}",
    )


def process_order_payment(event_data: OrderEventData) -> PaymentRecord:
    """Process a payment for an incoming order event.

    This is the main entry point called by the Service Bus consumer.
    Chains: currency conversion → gateway processing → PaymentRecord.

    For zero-decimal currencies the conversion step produces the wrong
    display_amount, and the gateway step raises ValueError.  That
    exception is intentionally *not* caught here so it can propagate
    to the consumer's error-handling logic.

    Args:
        event_data: The order event data from Service Bus.

    Returns:
        A PaymentRecord with the processing result.
    """
    logger.info(
        "Processing payment for order %s: %s %d",
        event_data.order_id,
        event_data.currency,
        event_data.amount,
    )

    # Convert from minor units to display amount
    # BUG: For JPY, this divides by 100 when it shouldn't
    display_amount = convert_to_display_amount(event_data.amount, event_data.currency)

    logger.info(
        "Converted amount: %s %s (minor: %d)",
        display_amount,
        event_data.currency,
        event_data.amount,
    )

    # Process through the payment gateway
    # For JPY orders, the display_amount will be too low and validation will fail
    gateway_response = process_payment_through_gateway(
        display_amount=display_amount,
        currency=event_data.currency,
        order_id=event_data.order_id,
    )

    # Build a PaymentRecord reflecting the gateway outcome.
    if gateway_response.success:
        logger.info(
            "Payment completed for order %s (txn: %s)",
            event_data.order_id,
            gateway_response.transaction_id,
        )
        return PaymentRecord(
            order_id=event_data.order_id,
            customer_id=event_data.customer_id,
            currency=event_data.currency,
            amount_minor=event_data.amount,
            amount_display=display_amount,
            status=PaymentStatus.COMPLETED,
        )

    logger.error(
        "Payment failed for order %s: %s",
        event_data.order_id,
        gateway_response.error,
    )
    return PaymentRecord(
        order_id=event_data.order_id,
        customer_id=event_data.customer_id,
        currency=event_data.currency,
        amount_minor=event_data.amount,
        amount_display=display_amount,
        status=PaymentStatus.FAILED,
        error_message=gateway_response.error,
    )
