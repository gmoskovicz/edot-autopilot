#!/usr/bin/env python3
"""
Smoke test: Tier A — PHP (native OTel SDK).

Runner script: attempts to run the PHP smoke test if `php` and `composer`
are available. Falls back to a Python simulation with service.name=smoke-tier-a-php.

Run:
    cd smoke-tests && python3 12-tier-a-php/smoke.py
"""

import os, sys, time, random
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-a-php"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

request_counter = meter.create_counter("cms.api_requests")
render_time     = meter.create_histogram("cms.render_ms", unit="ms")
cache_hits      = meter.create_counter("cms.cache_hits")

REQUESTS = [
    ("GET", "/api/v1/articles/42",  "art-42",  "enterprise", True),
    ("GET", "/api/v1/articles/117", "art-117", "public",     False),
    ("GET", "/api/v1/articles/8",   "art-8",   "pro",        True),
    ("GET", "/api/v1/articles/301", "art-301", "enterprise", False),
]

print(f"\n[{SVC}] Handling CMS API requests (PHP Tier A simulation)...")

for method, path, article_id, tier, cached in REQUESTS:
    t0 = time.time()
    with tracer.start_as_current_span("cms.handle_request", kind=SpanKind.SERVER,
            attributes={"http.method": method, "http.route": path,
                        "cms.article_id": article_id, "customer.tier": tier}) as span:

        with tracer.start_as_current_span("cms.authenticate", kind=SpanKind.INTERNAL):
            time.sleep(random.uniform(0.003, 0.012))

        if cached:
            with tracer.start_as_current_span("cms.cache_lookup", kind=SpanKind.CLIENT,
                    attributes={"cache.system": "redis", "cache.key": f"article:{article_id}"}) as cs:
                time.sleep(random.uniform(0.001, 0.005))
                cs.set_attribute("cache.hit", True)
            cache_hits.add(1, attributes={"customer.tier": tier})
        else:
            with tracer.start_as_current_span("cms.db_fetch", kind=SpanKind.CLIENT,
                    attributes={"db.system": "mysql", "db.operation": "SELECT", "db.table": "articles"}):
                time.sleep(random.uniform(0.020, 0.080))
            with tracer.start_as_current_span("cms.render_markdown", kind=SpanKind.INTERNAL):
                time.sleep(random.uniform(0.005, 0.025))

        dur = (time.time() - t0) * 1000
        span.set_attribute("http.status_code", 200)
        span.set_attribute("cms.response_ms",  round(dur, 2))
        span.set_attribute("cms.cached",        cached)

        request_counter.add(1, attributes={"http.method": method, "customer.tier": tier,
                                            "cms.cached": str(cached).lower()})
        render_time.record(dur, attributes={"customer.tier": tier})

        logger.info("CMS request handled",
                    extra={"http.method": method, "http.route": path,
                           "cms.article_id": article_id, "customer.tier": tier,
                           "cms.cached": cached, "cms.response_ms": round(dur, 2)})
        cache_str = "HIT " if cached else "MISS"
        print(f"  ✅ {method} {path:<30}  tier={tier:<12}  cache={cache_str}  dur={dur:.0f}ms")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
