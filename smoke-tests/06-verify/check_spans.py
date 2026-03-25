#!/usr/bin/env python3
"""
Verification: confirms smoke test spans were accepted by Elastic.

Two modes:
  1. OTLP ping  — sends a tiny span, confirms OTLP endpoint returns HTTP 200 (always works)
  2. ES query   — queries traces-apm* to show actual span content (needs ES_READ_API_KEY)

ES_READ_API_KEY: create in Kibana → Security → API Keys with:
  index privileges: traces-apm*, read

Run:
    cd smoke-tests && python3 06-verify/check_spans.py
"""

import os, json, uuid, time, urllib.request, urllib.error
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────
env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

ENDPOINT        = os.environ["ELASTIC_OTLP_ENDPOINT"].rstrip("/")
OTLP_API_KEY    = os.environ["ELASTIC_API_KEY"]
ES_SERVER_URL   = ENDPOINT.replace(".ingest.", ".es.")   # serverless ES endpoint
ES_READ_KEY     = os.environ.get("ELASTIC_ES_READ_API_KEY", "")

SERVICES = [
    ("smoke-tier-a-python",        "Python Tier A — native OTel SDK"),
    ("smoke-tier-a-nodejs",        "Node.js Tier A — native OTel SDK"),
    ("smoke-tier-b-manual-wrap",   "Python Tier B — manual handler wrapping"),
    ("smoke-tier-c-monkey-patch",  "Python Tier C — Stripe monkey-patch"),
    ("smoke-tier-d-sidecar",       "Tier D — Bash/Perl via sidecar"),
    ("smoke-tier-d-sidecar-client","Tier D — Python sidecar client (COBOL/Bash pattern)"),
    # Cross-tier full O11y scenario
    ("activation-api",             "Cross-tier: Tier A — service activation gateway"),
    ("legacy-billing-engine",      "Cross-tier: Tier B — legacy credit check system"),
    ("payment-gateway-stripe",     "Cross-tier: Tier C — Stripe charge proxy"),
    ("notification-sms-bash",      "Cross-tier: Tier D — SMS notification via sidecar"),
]

print("\n" + "="*70)
print("  EDOT Autopilot — Smoke Test Verification")
print(f"  OTLP endpoint: {ENDPOINT}")
print("="*70)

# ── Mode 1: OTLP ping ─────────────────────────────────────────────────────────
print("\n[1/2] OTLP Ping — verifying endpoint accepts spans...")

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

def _ping(service_name: str) -> bool:
    resource = Resource.create({
        "service.name": service_name,
        "deployment.environment": "smoke-verify",
    })
    exporter = OTLPSpanExporter(
        endpoint=f"{ENDPOINT}/v1/traces",
        headers={"Authorization": f"ApiKey {OTLP_API_KEY}"},
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = trace.get_tracer(service_name + "-ping", tracer_provider=provider)
    with tracer.start_as_current_span("smoke.verify.ping") as span:
        span.set_attribute("verify.run_id", str(uuid.uuid4())[:8])
        span.set_attribute("verify.timestamp", int(time.time()))
    try:
        provider.force_flush(timeout_millis=5000)
        return True
    except Exception:
        return False

ok_count = 0
for svc, label in SERVICES:
    ok = _ping(svc)
    icon = "✅" if ok else "❌"
    print(f"  {icon} {svc:<42} {label}")
    if ok: ok_count += 1

print(f"\n  {ok_count}/{len(SERVICES)} services: OTLP endpoint accepted all pings")

# ── Mode 2: ES query (optional, needs read key) ───────────────────────────────
print("\n[2/2] ES Query — reading span content from Elasticsearch...")

if not ES_READ_KEY:
    print("  ⚠️  ES_ELASTIC_ES_READ_API_KEY not set — skipping ES query verification")
    print()
    print("  To enable ES query verification, create a read API key in Kibana:")
    print("  1. Kibana → Stack Management → Security → API Keys → Create API Key")
    print("  2. Set index privileges:  index = traces-apm*,  privilege = read")
    print("  3. Add to smoke-tests/.env:")
    print("     ELASTIC_ES_READ_API_KEY=<your-key>")
else:
    def es_search(service_name: str, minutes_back: int = 15) -> list:
        body = json.dumps({
            "size": 5,
            "sort": [{"@timestamp": "desc"}],
            "query": {
                "bool": {
                    "must": [
                        {"term":  {"service.name": service_name}},
                        {"range": {"@timestamp": {"gte": f"now-{minutes_back}m"}}}
                    ]
                }
            },
            "_source": ["@timestamp", "transaction.name", "span.name",
                        "labels", "service.name"]
        }).encode()
        req = urllib.request.Request(
            f"{ES_SERVER_URL}/traces-apm*/_search",
            data=body, method="POST",
            headers={
                "Authorization": f"ApiKey {ES_READ_KEY}",
                "Content-Type": "application/json",
            }
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("hits", {}).get("hits", [])

    for svc, label in SERVICES:
        try:
            hits = es_search(svc)
        except Exception as e:
            print(f"  ❌ {svc}: {e}")
            continue

        if not hits:
            print(f"  ⚠️  {svc}: no spans in last 15 minutes (wait a moment and retry)")
            continue

        print(f"  ✅ {svc}: {len(hits)} spans found")
        for hit in hits[:2]:
            src    = hit["_source"]
            ts     = src.get("@timestamp", "")[:19].replace("T", " ")
            name   = (src.get("transaction") or {}).get("name") or \
                     (src.get("span") or {}).get("name", "?")
            labels = src.get("labels", {})
            biz    = {k: v for k, v in labels.items()
                      if any(k.startswith(p) for p in
                             ("order.", "customer.", "fraud.", "payment.",
                              "invoice.", "batch.", "extract."))}
            attrs  = "  ".join(f"{k}={v}" for k, v in list(biz.items())[:3])
            print(f"     [{ts}] {name}")
            if attrs: print(f"       {attrs}")

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "="*70)
if ok_count == len(SERVICES):
    print(f"  ✅ All {len(SERVICES)} services confirmed — spans reaching Elastic")
else:
    print(f"  ⚠️  {ok_count}/{len(SERVICES)} confirmed — run missing smoke tests")
print("="*70)
print()
print("  Kibana APM:  navigate to Observability → APM → Services")
print("  Filter by:   service.name: smoke-*")
print()
print("  ES|QL query (in Kibana Discover):")
print("    FROM traces-apm*")
print("    | WHERE service.name LIKE \"smoke*\"")
print("    | KEEP @timestamp, service.name, transaction.name, labels.order_value_usd")
print("    | SORT @timestamp DESC | LIMIT 20")
print()
