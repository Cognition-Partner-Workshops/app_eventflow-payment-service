"""Azure Service Bus consumer for order events.

Runs a background thread that long-polls an Azure Service Bus queue for
OrderCreated events, processes payments, and notifies the order service of
the outcome.  The threading model is intentionally simple (single consumer
thread + threading.Event for shutdown signalling) because the Service Bus
SDK's receive loop is blocking.

Message lifecycle:
  receive → parse JSON → validate as OrderCreatedEvent → process payment
  → complete (success) or abandon (failure) the message on the broker.

Failure modes:
  - Malformed JSON        → logged and skipped (message completed to avoid poison-pill loop).
  - ValueError (e.g. below-threshold amount) → order status set to "failed",
    message abandoned so Service Bus can retry or dead-letter it.
  - Transient Service Bus errors → reconnect with 10 s backoff.
"""

import json
import logging
import threading

import httpx
from azure.servicebus import ServiceBusClient
from azure.servicebus.exceptions import ServiceBusError

from app.config import settings
from app.models import OrderCreatedEvent, PaymentRecord
from app.processor import process_order_payment

logger = logging.getLogger(__name__)

# In-memory store for processed payments (demo purposes).
# A production system would persist these to a database.
payments: dict[str, PaymentRecord] = {}

# Module-level state for the single consumer thread.
# _stop_event is checked in the inner receive loop *and* used as a
# sleep primitive (wait(timeout=N)) for backoff, so that setting the
# event also interrupts any ongoing backoff sleep for fast shutdown.
_consumer_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _update_order_status(order_id: str, status: str) -> None:
    """HTTP PATCH callback to the order service to reflect payment outcome.

    Best-effort: failures are logged but never propagated, so a callback
    failure won't cause the message to be abandoned or retried.
    """
    if not settings.order_service_url:
        logger.debug("ORDER_SERVICE_URL not set — skipping status callback")
        return
    url = f"{settings.order_service_url}/api/orders/{order_id}/status"
    try:
        response = httpx.patch(url, json={"status": status}, timeout=5.0)
        if response.status_code == 200:
            logger.info("Order %s status updated to %s", order_id, status)
        else:
            logger.warning(
                "Failed to update order %s status: HTTP %d",
                order_id,
                response.status_code,
            )
    except Exception:
        logger.warning("Could not reach order service to update order %s", order_id)


def _process_message(message_body: str) -> None:
    """Parse and process a single Service Bus message.

    Orchestrates the full message pipeline: deserialise → validate →
    process payment → store result → callback to order service.

    Error handling strategy:
      - JSONDecodeError: swallowed (logged).  The caller will *complete*
        the message so it isn't retried as a poison pill.
      - ValueError: re-raised after attempting to mark the order as
        failed.  The caller will *abandon* the message.
      - Any other exception: re-raised immediately for abandonment.

    Args:
        message_body: JSON string of the OrderCreated event.
    """
    try:
        event_dict = json.loads(message_body)
        event = OrderCreatedEvent(**event_dict)

        logger.info(
            "Received OrderCreated event: order_id=%s, currency=%s, amount=%d",
            event.data.order_id,
            event.data.currency,
            event.data.amount,
        )

        # Process the payment — this is where JPY orders will crash
        # because of the zero-decimal currency conversion bug in processor.py.
        payment = process_order_payment(event.data)
        payments[payment.payment_id] = payment

        logger.info(
            "Payment %s for order %s: status=%s",
            payment.payment_id,
            payment.order_id,
            payment.status.value,
        )

        # Callback to order service to update order status
        _update_order_status(event.data.order_id, payment.status.value)

    except json.JSONDecodeError:
        # Malformed payload — nothing useful to retry, so we let the
        # caller complete the message rather than re-raising.
        logger.exception("Failed to parse message body as JSON")
    except ValueError:
        # Raised by validate_payment_amount when the (mis-converted)
        # display amount falls below the currency's minimum threshold.
        # This is the primary crash path for zero-decimal currencies.
        logger.exception(
            "Payment processing failed — unhandled validation error"
        )
        # Best-effort status update before re-raising to abandon.
        try:
            _update_order_status(event.data.order_id, "failed")
        except Exception:
            logger.warning("Could not update order status to failed")
        raise
    except Exception:
        # Catch-all: re-raise so the caller abandons the message.
        logger.exception("Unexpected error processing message")
        raise


def _consumer_loop() -> None:
    """Background loop that consumes messages from Service Bus.

    Structure (two nested context managers):
      outer `with client:`       — keeps the AMQP connection open
      inner `with receiver:`     — keeps the link/session to the queue open
      innermost while-loop       — polls for batches of up to 10 messages

    If the Service Bus connection drops, the outer try/except catches
    ServiceBusError, waits 10 s (interruptible via _stop_event), and
    re-enters the outer while-loop to create a fresh client + receiver.
    """
    if not settings.azure_servicebus_connection_string:
        logger.warning("Service Bus connection string not set — consumer not started")
        return

    logger.info(
        "Starting Service Bus consumer on queue: %s",
        settings.azure_servicebus_queue_name,
    )

    while not _stop_event.is_set():
        try:
            client = ServiceBusClient.from_connection_string(
                settings.azure_servicebus_connection_string
            )
            with client:
                receiver = client.get_queue_receiver(
                    queue_name=settings.azure_servicebus_queue_name,
                    max_wait_time=5,  # seconds to wait if queue is empty
                )
                with receiver:
                    while not _stop_event.is_set():
                        messages = receiver.receive_messages(
                            max_message_count=10,
                            max_wait_time=5,
                        )
                        for message in messages:
                            try:
                                body = str(message)
                                _process_message(body)
                                # Success path: remove message from queue.
                                receiver.complete_message(message)
                            except Exception:
                                # Failure path: return message to queue so
                                # Service Bus can redeliver or dead-letter it.
                                logger.exception(
                                    "Failed to process message — abandoning"
                                )
                                receiver.abandon_message(message)

        except ServiceBusError:
            # Transient AMQP / auth errors — back off before reconnecting.
            # wait() returns immediately if _stop_event is set (shutdown).
            logger.exception("Service Bus connection error — retrying in 10s")
            _stop_event.wait(timeout=10)
        except Exception:
            logger.exception("Unexpected consumer error — retrying in 10s")
            _stop_event.wait(timeout=10)

    logger.info("Service Bus consumer stopped")


def start_consumer() -> None:
    """Start the background consumer thread.

    Safe to call multiple times; no-ops if the thread is already running.
    The thread is daemonic so it won't prevent interpreter shutdown.
    """
    global _consumer_thread
    if _consumer_thread is not None and _consumer_thread.is_alive():
        logger.warning("Consumer thread already running")
        return

    _stop_event.clear()
    _consumer_thread = threading.Thread(target=_consumer_loop, daemon=True, name="sb-consumer")
    _consumer_thread.start()
    logger.info("Consumer thread started")


def stop_consumer() -> None:
    """Signal the consumer thread to stop and wait for it to finish.

    Blocks up to 15 s for the thread to exit.  The _stop_event
    interrupts both the receive loop and any backoff sleeps.
    """
    global _consumer_thread
    _stop_event.set()
    if _consumer_thread is not None:
        _consumer_thread.join(timeout=15)
        _consumer_thread = None
    logger.info("Consumer thread stopped")


async def check_servicebus_health() -> bool:
    """Lightweight probe: open and immediately close a receiver.

    Used by the /health endpoint to verify credentials and network
    connectivity to the Service Bus namespace.
    """
    if not settings.azure_servicebus_connection_string:
        return False
    try:
        client = ServiceBusClient.from_connection_string(
            settings.azure_servicebus_connection_string
        )
        with client:
            receiver = client.get_queue_receiver(
                queue_name=settings.azure_servicebus_queue_name,
                max_wait_time=1,
            )
            with receiver:
                pass
        return True
    except ServiceBusError:
        logger.exception("Service Bus health check failed")
        return False
