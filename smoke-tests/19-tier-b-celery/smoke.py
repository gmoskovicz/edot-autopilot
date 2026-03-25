#!/usr/bin/env python3
"""
Smoke test: Tier B — Celery task queue (no OTel Celery integration).

Wraps Celery task execution manually by decorating the task function.
Business scenario: Monthly invoice generation batch — generate PDF invoices,
email them, record delivery confirmation.

Run:
    cd smoke-tests && python3 19-tier-b-celery/smoke.py
"""

import os, sys, uuid, time, random
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-b-celery"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

task_counter   = meter.create_counter("celery.tasks.executed")
task_latency   = meter.create_histogram("celery.task.duration_ms", unit="ms")
invoice_value  = meter.create_histogram("invoice.amount_usd", unit="USD")


# ── Tier B: Celery task wrapper ───────────────────────────────────────────────
def celery_task(name, queue="default"):
    """Wraps a Celery task function — applied once at definition."""
    def decorator(fn):
        def wrapped(*args, **kwargs):
            t0 = time.time()
            task_id = f"task-{uuid.uuid4().hex[:12]}"
            with tracer.start_as_current_span(
                f"celery.task.{name}", kind=SpanKind.SERVER,
                attributes={"celery.task_name": name, "celery.queue": queue,
                            "celery.task_id": task_id},
            ) as span:
                try:
                    result = fn(*args, **kwargs)
                    span.set_attribute("celery.task_status", "success")
                    task_counter.add(1, attributes={"celery.task_name": name,
                                                     "celery.status": "success"})
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(StatusCode.ERROR, str(e))
                    task_counter.add(1, attributes={"celery.task_name": name,
                                                     "celery.status": "failed"})
                    raise
                finally:
                    task_latency.record((time.time() - t0) * 1000,
                                        attributes={"celery.task_name": name,
                                                    "celery.queue": queue})
        return wrapped
    return decorator


# ── Celery tasks — UNCHANGED ──────────────────────────────────────────────────
@celery_task("generate_invoice", queue="billing")
def generate_invoice(customer_id, billing_period, amount):
    invoice_id = f"INV-{uuid.uuid4().hex[:8].upper()}"

    with tracer.start_as_current_span("invoice.pdf.generate", kind=SpanKind.CLIENT,
        attributes={"invoice.id": invoice_id, "customer.id": customer_id,
                    "invoice.amount_usd": amount}) as span:
        time.sleep(0.03)
        span.set_attribute("invoice.pages", random.randint(1, 4))
        span.set_attribute("invoice.format", "pdf")

    with tracer.start_as_current_span("invoice.email.send", kind=SpanKind.CLIENT,
        attributes={"invoice.id": invoice_id, "customer.id": customer_id}) as span:
        time.sleep(0.02)
        delivered = random.random() > 0.05
        span.set_attribute("email.delivered", delivered)
        span.set_attribute("email.provider", "sendgrid")
        if not delivered:
            span.set_status(StatusCode.ERROR, "email bounce")

    invoice_value.record(amount, attributes={"billing.period": billing_period})
    logger.info("invoice generated and dispatched",
                extra={"invoice.id": invoice_id, "customer.id": customer_id,
                       "invoice.amount_usd": amount, "billing.period": billing_period,
                       "email.delivered": delivered})
    return {"invoice_id": invoice_id, "delivered": delivered}


invoices = [
    ("CUST-ENT-001", "2026-02", 4200.00),
    ("CUST-PRO-042", "2026-02", 99.00),
    ("CUST-FREE-007","2026-02", 0.00),
    ("CUST-ENT-002", "2026-02", 8500.00),
    ("CUST-PRO-015", "2026-02", 99.00),
]

print(f"\n[{SVC}] Simulating Celery invoice batch (manual task wrapping)...")
for customer_id, period, amount in invoices:
    result = generate_invoice(customer_id, period, amount)
    icon = "✅" if result["delivered"] else "⚠️ "
    print(f"  {icon} {customer_id:<18}  ${amount:>8.2f}  "
          f"invoice={result['invoice_id']}  delivered={result['delivered']}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
