"""Payment processing logic.

This module converts order amounts from minor units (cents/smallest denomination)
to display amounts and validates the payment.

Currencies have different decimal places ("minor unit exponents"):
- Most currencies (USD, EUR, GBP) have 2 decimal places (cents)
- Zero-decimal currencies (JPY, KRW) have 0 decimal places
- Some currencies (BHD, KWD) have 3 decimal places (fils)

The conversion must use the correct exponent for each currency.
"""

import logging
from dataclasses import dataclass

from app.models import OrderEventData, PaymentRecord, PaymentStatus

logger = logging.getLogger(__name__)

# Number of decimal places (minor unit exponent) for each currency.
# Zero-decimal currencies like JPY and KRW have an exponent of 0,
# meaning the amount is already in the base unit and should NOT be divided.
CURRENCY_DECIMAL_PLACES: dict[str, int] = {
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "JPY": 0,
    "KRW": 0,
    "CHF": 2,
    "CAD": 2,
    "AUD": 2,
    "CNY": 2,
    "INR": 2,
    "BHD": 3,
    "KWD": 3,
}

# Minimum transaction thresholds in display currency units
# These represent the minimum billable amount for each currency
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

    The conversion uses the currency's decimal places to determine the
    correct divisor. Zero-decimal currencies (JPY, KRW) are not divided.
    """
    decimal_places = CURRENCY_DECIMAL_PLACES.get(currency, 2)
    return amount_minor / (10 ** decimal_places)


def validate_payment_amount(display_amount: float, currency: str) -> None:
    """Validate that the payment amount meets minimum thresholds.

    Args:
        display_amount: Amount in display format.
        currency: ISO 4217 currency code.

    Raises:
        ValueError: If the amount is below the minimum threshold.
    """
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

    Args:
        display_amount: Amount in display format.
        currency: ISO 4217 currency code.
        order_id: The order being paid for.

    Returns:
        A GatewayResponse indicating success or failure.
    """
    # Validate minimum amount
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
    display_amount = convert_to_display_amount(event_data.amount, event_data.currency)

    logger.info(
        "Converted amount: %s %s (minor: %d)",
        display_amount,
        event_data.currency,
        event_data.amount,
    )

    # Process through the payment gateway
    gateway_response = process_payment_through_gateway(
        display_amount=display_amount,
        currency=event_data.currency,
        order_id=event_data.order_id,
    )

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
