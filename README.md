# EventFlow Payment Service

**System 2** in the EventFlow event-driven architecture demo.

A FastAPI service that consumes `OrderCreated` events from Azure Service Bus and processes payments. This service contains a known bug with zero-decimal currencies (JPY, KRW) that demonstrates the demo's incident response narrative.

## Overview

The EventFlow architecture consists of two primary services:

| Service | Role | Description |
|---|---|---|
| **Order Service** (System 1) | Event producer | Receives customer orders via REST API and publishes `OrderCreated` events to Azure Service Bus |
| **Payment Service** (System 2) | Event consumer | Subscribes to `OrderCreated` events, processes payments, and reports the result back to the Order Service |

This **Payment Service** is responsible for:

1. Consuming `OrderCreated` events from an Azure Service Bus queue
2. Converting order amounts from minor currency units (e.g., cents) to display amounts
3. Validating payments against minimum transaction thresholds
4. Simulating payment gateway processing
5. Storing payment records in memory
6. Calling back to the Order Service to update order status (`completed` or `failed`)

## Architecture Role

```
Order Service (System 1)
        |
        v
Azure Service Bus --> [Payment Service] --> Payment Processing
                            |                      |
                            |                      v
                            |               Order Service callback
                            v                (status update)
                     Application Insights
                            |
                            v
                     Alert Rule (on error spike)
                            |
                            v
                     Devin API (investigate + fix)
```

## Payment Processing Flow

The end-to-end flow when an `OrderCreated` event arrives:

1. **Message consumption** -- The background Service Bus consumer thread receives a message from the `order-events` queue.
2. **Event parsing** -- The raw JSON message is deserialized into an `OrderCreatedEvent` Pydantic model.
3. **Currency conversion** -- The amount in minor units (e.g., `10997` cents) is converted to a display amount (e.g., `109.97` USD) via `convert_to_display_amount()`.
4. **Gateway validation** -- The display amount is checked against per-currency minimum transaction thresholds via `validate_payment_amount()`.
5. **Gateway processing** -- The payment is submitted to the simulated payment gateway (`process_payment_through_gateway()`), which returns a transaction ID on success.
6. **Payment record creation** -- A `PaymentRecord` is created with the result (status `completed` or `failed`) and stored in the in-memory payments dictionary.
7. **Order status callback** -- An HTTP PATCH request is sent to the Order Service at `ORDER_SERVICE_URL/api/orders/{order_id}/status` to update the order's payment status.

### Minimum Transaction Thresholds

The payment gateway enforces minimum transaction amounts per currency (in display units):

| Currency | Minimum Amount | Description |
|---|---|---|
| USD | $0.50 | US Dollar |
| EUR | 0.50 | Euro |
| GBP | 0.30 | British Pound |
| JPY | 500 | Japanese Yen |
| KRW | 500 | South Korean Won |
| CHF | 0.50 | Swiss Franc |
| CAD | 0.50 | Canadian Dollar |
| AUD | 0.50 | Australian Dollar |
| CNY | 3.00 | Chinese Yuan |
| INR | 50.00 | Indian Rupee |

Any other currency defaults to a minimum threshold of **0.50** in its display unit.

## Features

- Azure Service Bus consumer for `OrderCreated` events
- Payment processing with currency conversion
- Order status callback to the Order Service
- Health check and readiness endpoints
- Structured logging with correlation IDs
- OpenTelemetry instrumentation for Azure Monitor
- In-memory payment record storage with REST API access

## The Bug (Demo Narrative)

The payment processor converts amounts from the smallest currency unit to display amounts by dividing by 100 (assuming all currencies have two decimal places). This works for USD, EUR, GBP but **fails for zero-decimal currencies** like JPY and KRW where the amount is already in the base unit.

When a JPY order arrives:
- Amount `15800` (yen) gets divided by 100 -> `158.00`
- Validation expects amount >= smallest billable unit in display currency
- `158.00` JPY is below the minimum threshold of `500` JPY -> **unhandled `ValueError`**

This bug is intentionally present on the `main` branch to demonstrate:
1. CI tests passing (they only cover USD/EUR)
2. Production crash on JPY input
3. Devin AI investigating logs and opening a fix PR

## Tech Stack

- **Python 3.11+**
- **FastAPI** -- async web framework with automatic OpenAPI docs
- **Azure Service Bus SDK** -- message consumption from queues
- **OpenTelemetry + Azure Monitor** -- distributed tracing and telemetry
- **Pydantic v2** -- data validation and settings management
- **pydantic-settings** -- environment variable configuration with `.env` file support
- **httpx** -- async/sync HTTP client for Order Service callbacks
- **structlog** -- structured logging
- **Poetry** -- dependency management
- **Ruff** -- fast Python linter

## Project Structure

```
app_eventflow-payment-service/
├── app/
│   ├── __init__.py          # Package marker
│   ├── main.py              # FastAPI entry point with lifespan management
│   ├── config.py            # Pydantic Settings for environment variable configuration
│   ├── models.py            # Pydantic models for events, payments, and API responses
│   ├── consumer.py          # Azure Service Bus background consumer thread
│   └── processor.py         # Payment processing logic and currency conversion
├── tests/
│   ├── __init__.py          # Package marker
│   ├── conftest.py          # Shared pytest fixtures (test client, sample event data)
│   └── test_processor.py    # Tests for payment processing (USD/EUR only)
├── .github/
│   └── workflows/
│       ├── ci.yml           # CI pipeline: lint (Ruff) + tests (pytest) + Docker build
│       └── cd.yml           # CD pipeline: build and deploy to Azure Container Apps
├── .env.example             # Example environment variable file
├── Dockerfile               # Multi-stage Docker build
├── pyproject.toml           # Poetry project config, Ruff settings, pytest config
└── README.md                # This file
```

### Module Details

| Module | Purpose |
|---|---|
| `app/main.py` | FastAPI application entry point. Manages the application lifespan (starts/stops the Service Bus consumer on startup/shutdown), configures CORS middleware, and defines the health, readiness, and payment API endpoints. |
| `app/config.py` | Application configuration using `pydantic-settings`. Reads environment variables (with `.env` file fallback) into a typed `Settings` object. Includes Service Bus connection details, Application Insights key, Order Service URL, and general app settings. |
| `app/models.py` | Pydantic data models: `PaymentStatus` enum (`pending`, `completed`, `failed`), `OrderItem` for line items, `OrderCreatedEvent` and `OrderEventData` for inbound Service Bus messages, and `PaymentRecord` for processed payment results. |
| `app/consumer.py` | Azure Service Bus background consumer. Runs in a daemon thread, receives messages in batches of up to 10, deserializes them as `OrderCreatedEvent`, passes them to the processor, stores results, and sends an HTTP callback to the Order Service with the payment status. |
| `app/processor.py` | Core payment logic. Converts amounts from minor units to display format, validates against minimum thresholds, and simulates a payment gateway. **Contains the intentional JPY/KRW bug** -- always divides by 100 regardless of currency. |
| `tests/conftest.py` | Shared pytest fixtures: a FastAPI `TestClient` and sample `OrderEventData` objects for USD and EUR orders. |
| `tests/test_processor.py` | Test suite covering currency conversion (USD, EUR, GBP, zero), end-to-end payment processing (USD, EUR, large USD), and health/readiness endpoints. **Intentionally does not test JPY/KRW** to allow the bug to pass CI. |

## Configuration

This service uses [`pydantic-settings`](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) to load configuration from environment variables. Settings are resolved in the following order of precedence (highest first):

1. **Environment variables** -- set directly in the shell or container runtime
2. **`.env` file** -- a dotenv file in the project root (see `.env.example` for a template)
3. **Defaults** -- fallback values defined in the `Settings` class

To get started, copy the example file and fill in your values:

```bash
cp .env.example .env
# Edit .env with your Azure Service Bus and Application Insights credentials
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `AZURE_SERVICEBUS_CONNECTION_STRING` | Azure Service Bus connection string | `""` *(required for event consumption)* |
| `AZURE_SERVICEBUS_QUEUE_NAME` | Queue name for order events | `order-events` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Azure Application Insights connection string | `""` *(optional -- enables telemetry)* |
| `ORDER_SERVICE_URL` | Base URL of the Order Service for status callbacks (e.g., `http://localhost:8001`) | `""` *(optional -- skips callback if not set)* |
| `LOG_LEVEL` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `ENVIRONMENT` | Deployment environment label (`development`, `staging`, `production`) | `development` |
| `SERVICE_NAME` | Service name for logging and health endpoints | `eventflow-payment-service` |
| `SERVICE_VERSION` | Service version reported in health endpoints | `1.0.0` |

## API Endpoints

### Health & Readiness

#### `GET /health`

Basic liveness probe. Always returns `200 OK` if the service is running.

**Response:**
```json
{
  "status": "healthy",
  "service": "eventflow-payment-service"
}
```

#### `GET /ready`

Readiness probe that checks downstream dependencies (Azure Service Bus connectivity).

**Response (healthy):**
```json
{
  "status": "ready",
  "service": "eventflow-payment-service",
  "servicebus_connected": true
}
```

**Response (degraded -- no Service Bus connection):**
```json
{
  "status": "degraded",
  "service": "eventflow-payment-service",
  "servicebus_connected": false
}
```

### Payments API

#### `GET /api/payments?limit=50`

List processed payments, sorted by most recent first.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `limit` | int | `50` | Maximum number of payments to return |

**Response:**
```json
[
  {
    "payment_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "order_id": "order-usd-001",
    "customer_id": "cust-001",
    "currency": "USD",
    "amount_minor": 10997,
    "amount_display": 109.97,
    "status": "completed",
    "processed_at": "2026-01-15T10:30:00Z",
    "error_message": null
  }
]
```

#### `GET /api/payments/{payment_id}`

Get a single payment record by ID.

**Response (success -- `200 OK`):**
```json
{
  "payment_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "order_id": "order-usd-001",
  "customer_id": "cust-001",
  "currency": "USD",
  "amount_minor": 10997,
  "amount_display": 109.97,
  "status": "completed",
  "processed_at": "2026-01-15T10:30:00Z",
  "error_message": null
}
```

**Response (not found -- `404 Not Found`):**
```json
{
  "detail": "Payment a1b2c3d4-e5f6-7890-abcd-ef1234567890 not found"
}
```

## Local Development

### Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/docs/#installation) 1.7+

### Setup

```bash
# Install dependencies
pip install poetry
poetry install

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your Azure Service Bus and Application Insights credentials

# Run the service (with hot reload)
poetry run uvicorn app.main:app --reload --port 8002
```

The service will be available at `http://localhost:8002`. Interactive API docs are generated automatically at `http://localhost:8002/docs` (Swagger UI) and `http://localhost:8002/redoc` (ReDoc).

> **Note:** Without a valid `AZURE_SERVICEBUS_CONNECTION_STRING`, the consumer thread will not start and the readiness endpoint will report `degraded`. The REST API endpoints will still function normally.

## Testing

### Running Tests

```bash
# Run all tests with verbose output
poetry run pytest -v --tb=short

# Run with coverage report
poetry run pytest --cov=app --cov-report=term-missing -v
```

### Test Coverage

The test suite in `tests/test_processor.py` covers:

| Test Class | What It Tests |
|---|---|
| `TestConvertToDisplayAmount` | Currency conversion for USD, EUR, GBP, and zero amounts |
| `TestProcessOrderPayment` | End-to-end payment processing for USD and EUR orders, including a large amount |
| `TestHealthEndpoints` | Health check, readiness probe (without Service Bus), and empty payments list |

> **Intentional gap:** The test suite does **not** include tests for zero-decimal currencies (JPY, KRW). This is by design for the demo narrative -- the tests pass in CI, but the service crashes in production when it receives a JPY or KRW order. See [The Bug (Demo Narrative)](#the-bug-demo-narrative) for details.

### Linting

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting, configured in `pyproject.toml`:

```bash
# Run the linter
poetry run ruff check app/ tests/

# Auto-fix issues where possible
poetry run ruff check --fix app/ tests/
```

Ruff is configured to target Python 3.11 with a line length of 100, checking for:
- `E` -- pycodestyle errors
- `F` -- Pyflakes
- `I` -- isort (import sorting)
- `N` -- pep8-naming
- `W` -- pycodestyle warnings
- `UP` -- pyupgrade

## Docker

### Build

```bash
docker build -t eventflow-payment-service .
```

The Dockerfile uses a multi-stage build to minimize the final image size:
1. **Builder stage** -- installs Poetry and project dependencies
2. **Runtime stage** -- copies only the installed packages and application code

### Run

```bash
# Run with an .env file
docker run -p 8002:8002 --env-file .env eventflow-payment-service

# Run with individual environment variables
docker run -p 8002:8002 \
  -e AZURE_SERVICEBUS_CONNECTION_STRING="Endpoint=sb://..." \
  -e AZURE_SERVICEBUS_QUEUE_NAME="order-events" \
  -e ORDER_SERVICE_URL="http://order-service:8001" \
  -e APPLICATIONINSIGHTS_CONNECTION_STRING="InstrumentationKey=..." \
  -e LOG_LEVEL="INFO" \
  -e ENVIRONMENT="production" \
  eventflow-payment-service
```

The container exposes port `8002` and sets `ENVIRONMENT=production` and `LOG_LEVEL=INFO` by default.

## CI/CD

The project includes two GitHub Actions workflows:

| Workflow | Trigger | Steps |
|---|---|---|
| **CI** (`.github/workflows/ci.yml`) | Push to `main`, PRs to `main` | Lint with Ruff, run pytest, build Docker image |
| **CD** (`.github/workflows/cd.yml`) | Push to `main` only | Log in to Azure, build and push to ACR, deploy to Azure Container Apps |

## Contributing

1. Create a feature branch from `main`
2. Make your changes (documentation, bug fixes, features)
3. Ensure linting passes: `poetry run ruff check app/ tests/`
4. Ensure tests pass: `poetry run pytest -v --tb=short`
5. Open a pull request targeting `main`

### Code Style

- Follow existing code conventions and patterns
- Use type hints for all function signatures
- Add docstrings to all public functions, classes, and modules
- Keep line length under 100 characters (enforced by Ruff)
