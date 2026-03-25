# Document Archival Service — blank fixture

A Python service that archives customer contracts to AWS S3.

## What it does

- Uploads PDF documents (contracts, DPAs, ToS) to a versioned S3 bucket
- Verifies the upload by fetching the object back
- Generates presigned download URLs with 24-hour TTL

## SDK used

**boto3** — the AWS SDK for Python. `boto3.client("s3")` returns an S3 client
with `put_object`, `get_object`, and `generate_presigned_url` methods.

Since real AWS credentials are not available, a mock client is used that
simulates the same interface and return shapes.

## No observability

This app has no OpenTelemetry instrumentation. Run:

```
Observe this project.
```

The agent should assign **Tier C** (monkey-patch) because there is no official
`opentelemetry-instrumentation-boto3` library. It should wrap `put_object` and
`get_object` with `SpanKind.CLIENT` spans carrying `aws.s3.bucket`,
`aws.s3.key`, and `aws.s3.content_length` attributes.
