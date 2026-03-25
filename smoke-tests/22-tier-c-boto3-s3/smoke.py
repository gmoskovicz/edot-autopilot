#!/usr/bin/env python3
"""
Smoke test: Tier C — AWS SDK (boto3) S3 client (monkey-patched).

Patches boto3.client.put_object / get_object — existing call sites unchanged.
Business scenario: Document archival service — upload customer contracts to S3,
verify checksums, generate presigned URLs.

Run:
    cd smoke-tests && python3 22-tier-c-boto3-s3/smoke.py
"""

import os, sys, uuid, time, hashlib, random
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-c-boto3-s3"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

s3_puts    = meter.create_counter("aws.s3.put_objects")
s3_gets    = meter.create_counter("aws.s3.get_objects")
s3_latency = meter.create_histogram("aws.s3.operation_ms", unit="ms")
s3_bytes   = meter.create_histogram("aws.s3.object_bytes", unit="bytes")


# ── Mock boto3 S3 client ──────────────────────────────────────────────────────
class _MockS3Client:
    def put_object(self, **kwargs):
        time.sleep(0.04)
        body = kwargs.get("Body", b"")
        return {"ETag": f'"{hashlib.md5(body).hexdigest()}"',
                "VersionId": uuid.uuid4().hex}

    def get_object(self, **kwargs):
        time.sleep(0.02)
        content = b"contract-pdf-content-stub"
        return {"Body": type("Body", (), {"read": lambda self: content})(),
                "ContentLength": len(content),
                "ETag": f'"{hashlib.md5(content).hexdigest()}"'}

    def generate_presigned_url(self, operation, Params, ExpiresIn=3600):
        key = Params.get("Key", "")
        return f"https://s3.amazonaws.com/{Params.get('Bucket')}/{key}?X-Amz-Expires={ExpiresIn}&sig=abc123"

class boto3:
    @staticmethod
    def client(service, **kwargs):
        return _MockS3Client()


# ── Tier C: patch put_object and get_object ───────────────────────────────────
_orig_put = _MockS3Client.put_object
_orig_get = _MockS3Client.get_object

def _instrumented_put(self, **kwargs):
    t0     = time.time()
    bucket = kwargs.get("Bucket", "")
    key    = kwargs.get("Key", "")
    body   = kwargs.get("Body", b"")
    size   = len(body) if isinstance(body, bytes) else 0
    with tracer.start_as_current_span("aws.s3.put_object", kind=SpanKind.CLIENT,
        attributes={"aws.s3.bucket": bucket, "aws.s3.key": key,
                    "aws.s3.content_length": size, "aws.service": "s3",
                    "aws.operation": "PutObject"}) as span:
        result = _orig_put(self, **kwargs)
        dur = (time.time() - t0) * 1000
        span.set_attribute("aws.s3.etag", result["ETag"])
        s3_puts.add(1, attributes={"aws.s3.bucket": bucket})
        s3_latency.record(dur, attributes={"aws.s3.operation": "put"})
        s3_bytes.record(size,  attributes={"aws.s3.operation": "put"})
        logger.info("S3 object uploaded", extra={"aws.s3.bucket": bucket, "aws.s3.key": key,
                    "aws.s3.etag": result["ETag"], "aws.s3.content_length": size})
        return result

def _instrumented_get(self, **kwargs):
    t0     = time.time()
    bucket = kwargs.get("Bucket", "")
    key    = kwargs.get("Key", "")
    with tracer.start_as_current_span("aws.s3.get_object", kind=SpanKind.CLIENT,
        attributes={"aws.s3.bucket": bucket, "aws.s3.key": key,
                    "aws.service": "s3", "aws.operation": "GetObject"}) as span:
        result = _orig_get(self, **kwargs)
        dur  = (time.time() - t0) * 1000
        size = result.get("ContentLength", 0)
        span.set_attribute("aws.s3.content_length", size)
        span.set_attribute("aws.s3.etag", result.get("ETag", ""))
        s3_gets.add(1, attributes={"aws.s3.bucket": bucket})
        s3_latency.record(dur,  attributes={"aws.s3.operation": "get"})
        s3_bytes.record(size,   attributes={"aws.s3.operation": "get"})
        logger.info("S3 object downloaded", extra={"aws.s3.bucket": bucket, "aws.s3.key": key,
                    "aws.s3.content_length": size})
        return result

_MockS3Client.put_object = _instrumented_put   # ← patch
_MockS3Client.get_object = _instrumented_get   # ← patch


# ── Existing application code — ZERO CHANGES ─────────────────────────────────
def archive_contract(customer_id, doc_type, content):
    s3 = boto3.client("s3", region_name="us-east-1")
    key = f"contracts/{customer_id}/{doc_type}-{uuid.uuid4().hex[:8]}.pdf"
    s3.put_object(Bucket="company-contracts-prod", Key=key, Body=content)
    s3.get_object(Bucket="company-contracts-prod", Key=key)
    url = s3.generate_presigned_url("get_object",
        Params={"Bucket": "company-contracts-prod", "Key": key}, ExpiresIn=86400)
    return {"key": key, "presigned_url": url}


contracts = [
    ("CUST-ENT-001", "master-services-agreement", b"MSA PDF content... " * 100),
    ("CUST-PRO-042", "subscription-agreement",    b"Sub agreement PDF..." * 50),
    ("CUST-ENT-002", "data-processing-addendum",  b"DPA PDF content..." * 80),
    ("CUST-FREE-007","terms-of-service",           b"TOS PDF content..." * 20),
]

print(f"\n[{SVC}] Archiving contracts via patched boto3 S3...")
for cust, doc_type, content in contracts:
    result = archive_contract(cust, doc_type, content)
    print(f"  ✅ {cust:<18}  {doc_type:<30}  key={result['key'].split('/')[-1]}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
