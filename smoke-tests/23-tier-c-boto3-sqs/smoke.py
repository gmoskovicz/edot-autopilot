#!/usr/bin/env python3
"""
Smoke test: Tier C — AWS SQS via boto3 (monkey-patched).

Patches SQS send_message / receive_message / delete_message.
Business scenario: Order fulfillment queue — publish orders to SQS,
warehouse picks them up, messages deleted after processing.

Run:
    cd smoke-tests && python3 23-tier-c-boto3-sqs/smoke.py
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

SVC = "smoke-tier-c-boto3-sqs"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

_msg_store = []  # simulated queue

sqs_sends    = meter.create_counter("aws.sqs.messages_sent")
sqs_receives = meter.create_counter("aws.sqs.messages_received")
sqs_deletes  = meter.create_counter("aws.sqs.messages_deleted")
sqs_latency  = meter.create_histogram("aws.sqs.operation_ms", unit="ms")


class _MockSQSClient:
    QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789/order-fulfillment-prod"

    def send_message(self, **kwargs):
        time.sleep(0.01)
        msg_id = str(uuid.uuid4())
        _msg_store.append({"MessageId": msg_id, "Body": kwargs.get("MessageBody", ""),
                           "ReceiptHandle": uuid.uuid4().hex})
        return {"MessageId": msg_id, "MD5OfMessageBody": "abc123"}

    def receive_message(self, **kwargs):
        time.sleep(0.01)
        msgs = _msg_store[:kwargs.get("MaxNumberOfMessages", 1)]
        return {"Messages": msgs} if msgs else {}

    def delete_message(self, **kwargs):
        time.sleep(0.005)
        handle = kwargs.get("ReceiptHandle", "")
        global _msg_store
        _msg_store = [m for m in _msg_store if m.get("ReceiptHandle") != handle]
        return {}

class boto3:
    @staticmethod
    def client(service, **kwargs):
        return _MockSQSClient()


_orig_send = _MockSQSClient.send_message
_orig_recv = _MockSQSClient.receive_message
_orig_del  = _MockSQSClient.delete_message

def _instrumented_send(self, **kwargs):
    t0 = time.time()
    queue = kwargs.get("QueueUrl", "").split("/")[-1]
    with tracer.start_as_current_span("aws.sqs.send_message", kind=SpanKind.CLIENT,
        attributes={"aws.sqs.queue": queue, "aws.service": "sqs",
                    "aws.operation": "SendMessage"}) as span:
        result = _orig_send(self, **kwargs)
        dur = (time.time() - t0) * 1000
        span.set_attribute("aws.sqs.message_id", result["MessageId"])
        sqs_sends.add(1, attributes={"aws.sqs.queue": queue})
        sqs_latency.record(dur, attributes={"aws.sqs.operation": "send"})
        logger.info("SQS message sent", extra={"aws.sqs.queue": queue,
                    "aws.sqs.message_id": result["MessageId"]})
        return result

def _instrumented_recv(self, **kwargs):
    t0 = time.time()
    queue = kwargs.get("QueueUrl", "").split("/")[-1]
    with tracer.start_as_current_span("aws.sqs.receive_message", kind=SpanKind.CLIENT,
        attributes={"aws.sqs.queue": queue, "aws.service": "sqs",
                    "aws.operation": "ReceiveMessage"}) as span:
        result = _orig_recv(self, **kwargs)
        msgs = result.get("Messages", [])
        span.set_attribute("aws.sqs.messages_received", len(msgs))
        sqs_receives.add(len(msgs), attributes={"aws.sqs.queue": queue})
        sqs_latency.record((time.time() - t0) * 1000, attributes={"aws.sqs.operation": "receive"})
        return result

def _instrumented_del(self, **kwargs):
    t0 = time.time()
    queue = kwargs.get("QueueUrl", "").split("/")[-1]
    with tracer.start_as_current_span("aws.sqs.delete_message", kind=SpanKind.CLIENT,
        attributes={"aws.sqs.queue": queue, "aws.service": "sqs",
                    "aws.operation": "DeleteMessage"}) as span:
        result = _orig_del(self, **kwargs)
        sqs_deletes.add(1, attributes={"aws.sqs.queue": queue})
        sqs_latency.record((time.time() - t0) * 1000, attributes={"aws.sqs.operation": "delete"})
        return result

_MockSQSClient.send_message    = _instrumented_send
_MockSQSClient.receive_message = _instrumented_recv
_MockSQSClient.delete_message  = _instrumented_del


def publish_order(order):
    sqs = boto3.client("sqs", region_name="us-east-1")
    resp = sqs.send_message(
        QueueUrl=_MockSQSClient.QUEUE_URL,
        MessageBody=json.dumps(order),
        MessageGroupId=order["warehouse_id"],
    )
    return resp

def process_orders():
    sqs = boto3.client("sqs", region_name="us-east-1")
    resp = sqs.receive_message(QueueUrl=_MockSQSClient.QUEUE_URL, MaxNumberOfMessages=10)
    for msg in resp.get("Messages", []):
        order = json.loads(msg["Body"])
        logger.info("order dispatched to warehouse",
                    extra={"order.id": order["id"], "fulfillment.warehouse_id": order["warehouse_id"],
                           "order.items": order["items"], "order.value_usd": order["value_usd"]})
        sqs.delete_message(QueueUrl=_MockSQSClient.QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])


orders = [
    {"id": f"ORD-{uuid.uuid4().hex[:6].upper()}", "warehouse_id": "WH-EAST-01",
     "items": 3, "value_usd": 189.99, "customer_tier": "enterprise"},
    {"id": f"ORD-{uuid.uuid4().hex[:6].upper()}", "warehouse_id": "WH-WEST-02",
     "items": 1, "value_usd": 29.99,  "customer_tier": "free"},
    {"id": f"ORD-{uuid.uuid4().hex[:6].upper()}", "warehouse_id": "WH-EAST-01",
     "items": 7, "value_usd": 892.50, "customer_tier": "pro"},
]

print(f"\n[{SVC}] Publishing + consuming orders via patched boto3 SQS...")
for order in orders:
    resp = publish_order(order)
    print(f"  ✅ published {order['id']}  ${order['value_usd']:.2f}  "
          f"warehouse={order['warehouse_id']}  msg={resp['MessageId'][:8]}...")
process_orders()
print(f"  ✅ processed {len(orders)} orders from queue")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
