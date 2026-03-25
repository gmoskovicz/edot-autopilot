#!/usr/bin/env python3
"""
Smoke test: Tier C — pika RabbitMQ client (monkey-patched).

Patches basic_publish on the channel.
Business scenario: Domain event bus — publish OrderCreated, PaymentReceived,
ShipmentDispatched events to a fanout exchange.

Run:
    cd smoke-tests && python3 29-tier-c-rabbitmq/smoke.py
"""

import os, sys, uuid, time, json
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-c-rabbitmq"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

msgs_published = meter.create_counter("rabbitmq.messages_published")
publish_latency= meter.create_histogram("rabbitmq.publish_ms", unit="ms")


class _MockChannel:
    def basic_publish(self, exchange, routing_key, body, properties=None, mandatory=False):
        time.sleep(0.005)
        return True

class _MockConnection:
    def channel(self):
        return _MockChannel()
    def close(self):
        pass
    def __enter__(self): return self
    def __exit__(self, *args): self.close()

class pika:
    class BlockingConnection:
        def __init__(self, params): pass
        def channel(self): return _MockChannel()
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *args): self.close()

    class ConnectionParameters:
        def __init__(self, host="localhost", port=5672, **kwargs):
            self.host = host

    class BasicProperties:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)


_orig_publish = _MockChannel.basic_publish

def _inst_publish(self, exchange, routing_key, body, properties=None, mandatory=False):
    t0 = time.time()
    body_str = body if isinstance(body, str) else body.decode("utf-8", errors="replace")
    with tracer.start_as_current_span("rabbitmq.basic_publish", kind=SpanKind.CLIENT,
        attributes={"messaging.system":       "rabbitmq",
                    "messaging.destination":  exchange,
                    "messaging.routing_key":  routing_key,
                    "messaging.body_length":  len(body)}) as span:
        try:
            payload = json.loads(body_str) if body_str.startswith("{") else {}
        except Exception:
            payload = {}
        span.set_attribute("event.type",     payload.get("event_type", ""))
        span.set_attribute("messaging.message_id", payload.get("event_id", uuid.uuid4().hex))
        result = _orig_publish(self, exchange, routing_key, body, properties, mandatory)
        dur = (time.time() - t0) * 1000
        msgs_published.add(1, attributes={"messaging.destination": exchange,
                                           "event.type": payload.get("event_type", "unknown")})
        publish_latency.record(dur, attributes={"messaging.destination": exchange})
        logger.info("rabbitmq message published",
                    extra={"messaging.destination": exchange,
                           "messaging.routing_key": routing_key,
                           "event.type": payload.get("event_type", ""),
                           "order.id": payload.get("order_id", "")})
        return result

_MockChannel.basic_publish = _inst_publish


def publish_event(channel, event_type, data):
    event = {"event_id": uuid.uuid4().hex, "event_type": event_type, **data}
    channel.basic_publish(
        exchange="domain.events",
        routing_key=event_type.lower().replace(".", "_"),
        body=json.dumps(event).encode(),
        properties=pika.BasicProperties(content_type="application/json",
                                         delivery_mode=2),
    )
    return event["event_id"]


with pika.BlockingConnection(pika.ConnectionParameters(host="rabbitmq.internal")) as conn:
    ch = conn.channel()
    events = [
        ("order.created",      {"order_id": f"ORD-{uuid.uuid4().hex[:6].upper()}", "amount_usd": 4200.00, "customer_tier": "enterprise"}),
        ("payment.received",   {"order_id": f"ORD-{uuid.uuid4().hex[:6].upper()}", "amount_usd": 4200.00, "payment_method": "wire"}),
        ("order.created",      {"order_id": f"ORD-{uuid.uuid4().hex[:6].upper()}", "amount_usd": 99.00,   "customer_tier": "pro"}),
        ("shipment.dispatched",{"order_id": f"ORD-{uuid.uuid4().hex[:6].upper()}", "carrier": "fedex",    "tracking": "FX123456"}),
    ]

    print(f"\n[{SVC}] Publishing domain events via patched pika/RabbitMQ...")
    for event_type, data in events:
        eid = publish_event(ch, event_type, data)
        print(f"  ✅ {event_type:<30}  event_id={eid[:12]}...")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
