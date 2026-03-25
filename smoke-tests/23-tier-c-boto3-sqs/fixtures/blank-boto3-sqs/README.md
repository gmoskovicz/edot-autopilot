# Order Fulfillment Queue — blank fixture

A Python service that publishes and consumes orders via AWS SQS.

## What it does

- Publishes warehouse orders to an SQS FIFO queue grouped by warehouse ID
- A consumer polls the queue, processes each order, then deletes the message
- Covers the full send → receive → delete message lifecycle

## SDK used

**boto3** — the AWS SDK for Python. `boto3.client("sqs")` returns an SQS client
with `send_message`, `receive_message`, and `delete_message` methods.

Since real AWS credentials are not available, a mock client is used that
simulates the same interface and return shapes using an in-process list.

## No observability

This app has no OpenTelemetry instrumentation. Run:

```
Observe this project.
```

The agent should assign **Tier C** (monkey-patch) because there is no official
`opentelemetry-instrumentation-boto3` library. It should wrap `send_message`,
`receive_message`, and `delete_message` with spans carrying
`messaging.system=aws_sqs`, `messaging.destination.name`, and
`messaging.message.id` attributes.
