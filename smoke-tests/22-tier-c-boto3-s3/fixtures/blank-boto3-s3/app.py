"""
Document Archival Service — AWS S3 via boto3

No observability. Run `Observe this project.` to add it.
"""

import uuid
import hashlib
import time


# ── Mock boto3 S3 client (simulates real boto3 without AWS credentials) ────────
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
        return (
            f"https://s3.amazonaws.com/{Params.get('Bucket')}/{key}"
            f"?X-Amz-Expires={ExpiresIn}&sig=abc123"
        )


class boto3:
    @staticmethod
    def client(service, **kwargs):
        return _MockS3Client()


# ── Application code ───────────────────────────────────────────────────────────

def archive_contract(customer_id, doc_type, content):
    """Upload a customer contract to S3, verify it, and return a presigned URL."""
    s3 = boto3.client("s3", region_name="us-east-1")
    key = f"contracts/{customer_id}/{doc_type}-{uuid.uuid4().hex[:8]}.pdf"

    s3.put_object(Bucket="company-contracts-prod", Key=key, Body=content)
    s3.get_object(Bucket="company-contracts-prod", Key=key)

    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": "company-contracts-prod", "Key": key},
        ExpiresIn=86400,
    )
    return {"key": key, "presigned_url": url}


if __name__ == "__main__":
    contracts = [
        ("CUST-ENT-001", "master-services-agreement", b"MSA PDF content... " * 100),
        ("CUST-PRO-042", "subscription-agreement",    b"Sub agreement PDF..." * 50),
        ("CUST-ENT-002", "data-processing-addendum",  b"DPA PDF content..." * 80),
        ("CUST-FREE-007", "terms-of-service",          b"TOS PDF content..." * 20),
    ]

    for cust, doc_type, content in contracts:
        result = archive_contract(cust, doc_type, content)
        print(f"Archived: {cust}/{doc_type} → {result['key']}")
