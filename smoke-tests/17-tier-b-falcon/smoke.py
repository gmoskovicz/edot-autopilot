#!/usr/bin/env python3
"""
Smoke test: Tier B — Falcon REST framework (no EDOT instrumentation).

Wraps Falcon responder methods manually.
Business scenario: Payment webhook receiver — process incoming Stripe webhook
events (charge.succeeded, payment.failed, dispute.created).

Run:
    cd smoke-tests && python3 17-tier-b-falcon/smoke.py
"""

import os, sys, uuid, time
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-b-falcon"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

webhook_counter  = meter.create_counter("webhook.events_received")
webhook_latency  = meter.create_histogram("webhook.processing_ms", unit="ms")
dispute_counter  = meter.create_counter("webhook.disputes_opened")


# ── Tier B: Falcon responder wrapper ─────────────────────────────────────────
def instrument_falcon_responder(resource_class, method="on_post", route="/"):
    original = getattr(resource_class, method)
    def wrapped(self, req, resp, **kwargs):
        t0 = time.time()
        with tracer.start_as_current_span(
            f"POST {route}", kind=SpanKind.SERVER,
            attributes={"http.method": "POST", "http.route": route, "framework": "falcon"},
        ) as span:
            original(self, req, resp, **kwargs)
            span.set_attribute("http.status_code", int(resp.status.split()[0]))
            webhook_latency.record((time.time() - t0) * 1000,
                                   attributes={"event.type": req.media.get("type", "unknown")})
    setattr(resource_class, method, wrapped)


# ── Falcon resource — UNCHANGED ───────────────────────────────────────────────
class MockResp:
    status = "200 OK"
    media  = {}

class WebhookResource:
    def on_post(self, req, resp, **kwargs):
        event = req.media
        event_type  = event.get("type")
        livemode    = event.get("livemode", False)
        event_data  = event.get("data", {}).get("object", {})
        amount_usd  = event_data.get("amount", 0) / 100

        webhook_counter.add(1, attributes={"event.type": event_type,
                                            "payment.livemode": str(livemode)})

        if event_type == "charge.succeeded":
            logger.info("charge.succeeded webhook processed",
                        extra={"event.type": event_type, "payment.amount_usd": amount_usd,
                               "payment.customer_id": event_data.get("customer"),
                               "payment.charge_id": event_data.get("id")})

        elif event_type == "payment_intent.payment_failed":
            logger.warning("payment failed webhook",
                           extra={"event.type": event_type, "payment.amount_usd": amount_usd,
                                  "payment.failure_code": event_data.get("last_payment_error", {}).get("code")})

        elif event_type == "charge.dispute.created":
            dispute_counter.add(1, attributes={"payment.livemode": str(livemode)})
            logger.error("dispute opened",
                         extra={"event.type": event_type, "payment.amount_usd": amount_usd,
                                "dispute.reason": event_data.get("reason"),
                                "dispute.id": event_data.get("id")})

        resp.status = "200 OK"
        resp.media  = {"received": True}


instrument_falcon_responder(WebhookResource, "on_post", "/webhooks/stripe")

resource = WebhookResource()
events = [
    {"type": "charge.succeeded",              "livemode": True,
     "data": {"object": {"id": f"ch_{uuid.uuid4().hex[:16]}", "amount": 420000, "customer": "cus_ent_001"}}},
    {"type": "charge.succeeded",              "livemode": True,
     "data": {"object": {"id": f"ch_{uuid.uuid4().hex[:16]}", "amount": 2999,   "customer": "cus_free_042"}}},
    {"type": "payment_intent.payment_failed", "livemode": True,
     "data": {"object": {"amount": 125000, "last_payment_error": {"code": "card_declined"}}}},
    {"type": "charge.dispute.created",        "livemode": True,
     "data": {"object": {"id": f"dp_{uuid.uuid4().hex[:16]}", "amount": 89900, "reason": "fraudulent"}}},
]

print(f"\n[{SVC}] Simulating Falcon webhook receiver (manual responder wrapping)...")
for event in events:
    req  = type("Req", (), {"media": event})()
    resp = MockResp()
    resource.on_post(req, resp)
    icon = "⚠️ " if "dispute" in event["type"] or "failed" in event["type"] else "✅"
    print(f"  {icon} {event['type']:<40}  "
          f"${event['data']['object'].get('amount', 0)/100:.2f}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
