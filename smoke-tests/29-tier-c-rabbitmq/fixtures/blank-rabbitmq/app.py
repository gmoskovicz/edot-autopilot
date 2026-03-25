"""
Domain Event Bus — RabbitMQ via pika

No observability. Run `Observe this project.` to add it.
"""

import uuid
import json
import time


# ── Mock pika (simulates real pika without a RabbitMQ broker) ─────────────────

class _MockChannel:
    def basic_publish(self, exchange, routing_key, body, properties=None, mandatory=False):
        time.sleep(0.005)
        return True


class _MockConnection:
    def channel(self):
        return _MockChannel()

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class pika:
    class BlockingConnection:
        def __init__(self, params):
            pass

        def channel(self):
            return _MockChannel()

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    class ConnectionParameters:
        def __init__(self, host="localhost", port=5672, **kwargs):
            self.host = host

    class BasicProperties:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)


# ── Application code ───────────────────────────────────────────────────────────

def publish_event(channel, event_type, data):
    """Publish a domain event to the fanout exchange."""
    event = {"event_id": uuid.uuid4().hex, "event_type": event_type, **data}
    channel.basic_publish(
        exchange="domain.events",
        routing_key=event_type.lower().replace(".", "_"),
        body=json.dumps(event).encode(),
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,
        ),
    )
    print(f"  Published: {event_type} (id={event['event_id'][:8]})")
    return event["event_id"]


if __name__ == "__main__":
    with pika.BlockingConnection(pika.ConnectionParameters(host="rabbitmq.internal")) as conn:
        ch = conn.channel()
        events = [
            ("order.created", {"order_id": f"ORD-{uuid.uuid4().hex[:6].upper()}",
                               "amount_usd": 4200.00, "customer_tier": "enterprise"}),
            ("payment.received", {"order_id": f"ORD-{uuid.uuid4().hex[:6].upper()}",
                                  "amount_usd": 4200.00, "payment_method": "wire"}),
            ("order.created", {"order_id": f"ORD-{uuid.uuid4().hex[:6].upper()}",
                               "amount_usd": 99.00, "customer_tier": "pro"}),
            ("shipment.dispatched", {"order_id": f"ORD-{uuid.uuid4().hex[:6].upper()}",
                                     "carrier": "fedex", "tracking": "FX123456"}),
        ]

        for event_type, data in events:
            publish_event(ch, event_type, data)

    print("All events published")
