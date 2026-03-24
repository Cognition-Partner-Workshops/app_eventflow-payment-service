"""Application configuration loaded from environment variables.

Uses pydantic-settings to read configuration from environment variables with
fallback to a ``.env`` file in the project root.  The resolution order is:

1. Environment variables (highest precedence)
2. ``.env`` file
3. Default values defined on the ``Settings`` class
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Payment Service configuration.

    Attributes:
        azure_servicebus_connection_string: Connection string for Azure Service Bus.
            Required for the background consumer to receive order events.
        azure_servicebus_queue_name: Name of the Service Bus queue to consume from.
        applicationinsights_connection_string: Connection string for Azure Application
            Insights.  When set, OpenTelemetry telemetry is exported to Azure Monitor.
        order_service_url: Base URL of the Order Service (System 1).  Used to send
            HTTP PATCH callbacks that update order status after payment processing.
            If empty, callbacks are silently skipped.
        log_level: Python logging level name (DEBUG, INFO, WARNING, ERROR).
        environment: Deployment environment label used in structured logs.
        service_name: Logical service name reported in health endpoints and logs.
        service_version: Service version reported in the ``/health`` endpoint.
    """

    # Azure Service Bus
    azure_servicebus_connection_string: str = ""
    azure_servicebus_queue_name: str = "order-events"

    # Azure Monitor
    applicationinsights_connection_string: str = ""

    # Order service callback
    order_service_url: str = ""

    # Application
    log_level: str = "INFO"
    environment: str = "development"
    service_name: str = "eventflow-payment-service"
    service_version: str = "1.0.0"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
