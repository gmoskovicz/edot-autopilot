# Domain Event Bus — blank fixture

A Python service that publishes domain events to a RabbitMQ fanout exchange.

## What it does

- Connects to RabbitMQ via `pika.BlockingConnection`
- Publishes `order.created`, `payment.received`, and `shipment.dispatched` events
- Each message is a JSON-encoded envelope with `event_id`, `event_type`, and business payload
- Messages are persistent (`delivery_mode=2`) and routed via `domain.events` exchange

## SDK used

**pika** — the pure-Python RabbitMQ client. Uses
`channel.basic_publish(exchange, routing_key, body, properties)`.

Since no RabbitMQ broker is available, a mock is used that simulates the
same interface with realistic latency.

## No observability

This app has no OpenTelemetry instrumentation. Run:

```
Observe this project.
```

The agent should assign **Tier C** (monkey-patch) because pika has no official
OTel instrumentation. It should wrap `Channel.basic_publish` with
`SpanKind.CLIENT` spans carrying `messaging.system=rabbitmq`,
`messaging.destination`, `messaging.routing_key`, and `event.type` attributes.
