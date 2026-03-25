#!/usr/bin/env python3
"""
Smoke test: Tier D — ColdFusion / CFML (sidecar simulation).

Simulates a ColdFusion web application submitting observability via the HTTP
sidecar. Business scenario: e-commerce CMS content publishing — product catalog
updates, cache invalidation, CDN purge, search index sync.

Run:
    cd smoke-tests && python3 46-tier-d-coldfusion/smoke.py
"""

import os, sys, time, random, uuid
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind

SVC = "smoke-tier-d-coldfusion"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

pages_published    = meter.create_counter("cf.pages_published")
cache_purges       = meter.create_counter("cf.cache_purges")
publish_duration   = meter.create_histogram("cf.publish_duration_ms", unit="ms")
db_query_count     = meter.create_counter("cf.db_queries")

PUBLISH_REQUESTS = [
    {"page_id": "CAT-ELECTRONICS-01", "type": "category",  "products": 48,  "images": 48,  "author": "m.johnson"},
    {"page_id": "PROD-SKU-WB4421",    "type": "product",   "products": 1,   "images": 8,   "author": "a.silva"},
    {"page_id": "PROMO-SUMMER-2026",  "type": "promotion", "products": 120, "images": 25,  "author": "k.chen"},
    {"page_id": "BLOG-TECH-UPDATE",   "type": "blog_post", "products": 0,   "images": 3,   "author": "r.park"},
]

def publish_content(req):
    t0 = time.time()
    version_id = uuid.uuid4().hex[:8]

    with tracer.start_as_current_span("CF.content_publish.cfm", kind=SpanKind.SERVER,
            attributes={"cf.template": "content_publish.cfm", "cf.page_id": req["page_id"],
                        "cf.content_type": req["type"], "cf.author": req["author"]}) as span:

        with tracer.start_as_current_span("CF.cfquery.SELECT_content", kind=SpanKind.CLIENT,
                attributes={"db.system": "mssql", "db.operation": "SELECT",
                            "db.table": "cms_content", "cf.cfquery": "getContentByID"}):
            time.sleep(random.uniform(0.02, 0.06))
            db_query_count.add(1, attributes={"db.operation": "SELECT"})

        with tracer.start_as_current_span("CF.cfquery.UPDATE_publish_status", kind=SpanKind.CLIENT,
                attributes={"db.system": "mssql", "db.operation": "UPDATE",
                            "db.table": "cms_content", "cf.cfquery": "publishContent"}):
            time.sleep(random.uniform(0.01, 0.04))
            db_query_count.add(1, attributes={"db.operation": "UPDATE"})

        with tracer.start_as_current_span("CF.cfcache.flushAll", kind=SpanKind.INTERNAL,
                attributes={"cf.operation": "cfcache", "cf.action": "flush",
                            "cf.cache_region": f"content_{req['type']}"}):
            time.sleep(random.uniform(0.005, 0.020))
            cache_purges.add(1, attributes={"cf.content_type": req["type"]})

        if req["images"] > 0:
            with tracer.start_as_current_span("CF.cfhttp.cdn_purge", kind=SpanKind.CLIENT,
                    attributes={"http.method": "POST", "cf.operation": "cfhttp",
                                "cdn.provider": "CloudFront", "cdn.files_purged": req["images"]}):
                time.sleep(random.uniform(0.05, 0.15))

        if req["products"] > 0:
            with tracer.start_as_current_span("CF.cfhttp.search_index_sync", kind=SpanKind.CLIENT,
                    attributes={"http.method": "POST", "cf.operation": "cfhttp",
                                "search.provider": "Elasticsearch", "search.docs_updated": req["products"]}):
                time.sleep(random.uniform(0.03, 0.10))

        dur = (time.time() - t0) * 1000
        span.set_attribute("cf.version_id",   version_id)
        span.set_attribute("cf.images_purged", req["images"])
        span.set_attribute("cf.products_indexed", req["products"])
        span.set_attribute("cf.publish_ms",    round(dur, 2))

        pages_published.add(1, attributes={"cf.content_type": req["type"]})
        publish_duration.record(dur, attributes={"cf.content_type": req["type"]})

        logger.info("content published",
                    extra={"cf.page_id": req["page_id"], "cf.content_type": req["type"],
                           "cf.author": req["author"], "cf.version_id": version_id,
                           "cf.images_purged": req["images"], "cf.publish_ms": round(dur, 2)})
    return version_id

print(f"\n[{SVC}] Simulating ColdFusion CMS content publishing pipeline...")
for req in PUBLISH_REQUESTS:
    vid = publish_content(req)
    print(f"  ✅ {req['page_id']:<28}  type={req['type']:<12}  v={vid}  by={req['author']}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
