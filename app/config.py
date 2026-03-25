"""Application configuration loaded from environment variables.

All settings can be overridden by setting the corresponding environment
variable (case-insensitive) or by adding an entry to a `.env` file in
the project root.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Payment Service configuration.

    Attributes:
        azure_servicebus_connection_string: Connection string for Azure Service
            Bus.  When empty the consumer thread is not started.
        azure_servicebus_queue_name: Name of the Service Bus queue to consume
            OrderCreated events from.
        applicationinsights_connection_string: Optional Azure Monitor
            connection string for distributed tracing.
        order_service_url: Base URL of the order service used for status
            callbacks after payment processing (e.g. ``http://order-svc:8000``).
            When empty, callbacks are skipped.
        log_level: Python log level name (DEBUG, INFO, WARNING, ERROR).
        environment: Deployment environment label (development, staging, production).
        service_name: Logical service name surfaced in health checks and logs.
        service_version: Semantic version reported in the OpenAPI spec.
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
