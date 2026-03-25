"""
Order Fulfillment Queue — AWS SQS via boto3

No observability. Run `Observe this project.` to add it.
"""

import uuid
import json
import time


# ── Mock boto3 SQS client (simulates real boto3 without AWS credentials) ───────
_msg_store = []  # in-process queue simulation


class _MockSQSClient:
    QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789/order-fulfillment-prod"

    def send_message(self, **kwargs):
        time.sleep(0.01)
        msg_id = str(uuid.uuid4())
        _msg_store.append({
            "MessageId": msg_id,
            "Body": kwargs.get("MessageBody", ""),
            "ReceiptHandle": uuid.uuid4().hex,
        })
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


# ── Application code ───────────────────────────────────────────────────────────

def publish_order(order):
    """Publish an order to the SQS fulfillment queue."""
    sqs = boto3.client("sqs", region_name="us-east-1")
    resp = sqs.send_message(
        QueueUrl=_MockSQSClient.QUEUE_URL,
        MessageBody=json.dumps(order),
        MessageGroupId=order["warehouse_id"],
    )
    return resp


def process_orders():
    """Consume orders from the queue and acknowledge them."""
    sqs = boto3.client("sqs", region_name="us-east-1")
    resp = sqs.receive_message(
        QueueUrl=_MockSQSClient.QUEUE_URL,
        MaxNumberOfMessages=10,
    )
    for msg in resp.get("Messages", []):
        order = json.loads(msg["Body"])
        print(f"Processing order {order['id']} for warehouse {order['warehouse_id']}")
        sqs.delete_message(
            QueueUrl=_MockSQSClient.QUEUE_URL,
            ReceiptHandle=msg["ReceiptHandle"],
        )


if __name__ == "__main__":
    orders = [
        {"id": f"ORD-{uuid.uuid4().hex[:6].upper()}", "warehouse_id": "WH-EAST-01",
         "items": 3, "value_usd": 189.99, "customer_tier": "enterprise"},
        {"id": f"ORD-{uuid.uuid4().hex[:6].upper()}", "warehouse_id": "WH-WEST-02",
         "items": 1, "value_usd": 29.99, "customer_tier": "free"},
        {"id": f"ORD-{uuid.uuid4().hex[:6].upper()}", "warehouse_id": "WH-EAST-01",
         "items": 7, "value_usd": 892.50, "customer_tier": "pro"},
    ]

    for order in orders:
        resp = publish_order(order)
        print(f"Published: {order['id']} → MessageId={resp['MessageId']}")

    process_orders()
    print("All orders processed")
