"""
Tier C — Monkey-patching the Stripe SDK (no native OTel plugin exists).

The Stripe Python SDK has no OpenTelemetry support. This module patches
stripe.Charge.create and stripe.PaymentIntent.create at import time.
Existing application code needs ZERO changes — just import this module first.

Usage:
    import stripe_instrumented  # patches Stripe at import time
    import stripe               # now instrumented automatically
    stripe.Charge.create(...)   # → emits a span to Elastic
"""

import os
import stripe
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import SpanKind

# ── Bootstrap (only if not already configured) ───────────────────────────────

def _bootstrap_otel():
    endpoint = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
    api_key  = os.environ.get("ELASTIC_API_KEY", "")
    svc_name = os.environ.get("OTEL_SERVICE_NAME", "stripe-tier-c")

    if not endpoint or not api_key:
        return  # already configured externally (e.g. by EDOT agent in Tier A service)

    resource = Resource.create({
        "service.name":           svc_name,
        "deployment.environment": os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "development"),
    })
    exporter = OTLPSpanExporter(
        endpoint=f"{endpoint}/v1/traces",
        headers={"Authorization": f"ApiKey {api_key}"},
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

_bootstrap_otel()
tracer = trace.get_tracer("stripe-instrumentation")

# ── Monkey-patches ─────────────────────────────────────────────────────────────

_orig_charge_create = stripe.Charge.create

def _patched_charge_create(**kwargs):
    with tracer.start_as_current_span(
        "stripe.charge.create",
        kind=SpanKind.CLIENT,
        attributes={
            "payment.provider":    "stripe",
            "payment.amount":      kwargs.get("amount"),
            "payment.currency":    kwargs.get("currency", "usd"),
            "payment.customer_id": kwargs.get("customer", ""),
            "payment.description": kwargs.get("description", ""),
        },
    ) as span:
        try:
            result = _orig_charge_create(**kwargs)
            span.set_attribute("payment.charge_id", result["id"])
            span.set_attribute("payment.status",    result["status"])
            span.set_attribute("payment.captured",  result.get("captured", False))
            return result
        except stripe.StripeError as e:
            span.record_exception(e)
            span.set_attribute("payment.error_code", getattr(e, "code", "unknown"))
            span.set_status(trace.StatusCode.ERROR, str(e))
            raise

stripe.Charge.create = _patched_charge_create


_orig_pi_create = stripe.PaymentIntent.create

def _patched_pi_create(**kwargs):
    with tracer.start_as_current_span(
        "stripe.payment_intent.create",
        kind=SpanKind.CLIENT,
        attributes={
            "payment.provider":    "stripe",
            "payment.amount":      kwargs.get("amount"),
            "payment.currency":    kwargs.get("currency", "usd"),
            "payment.customer_id": kwargs.get("customer", ""),
        },
    ) as span:
        try:
            result = _orig_pi_create(**kwargs)
            span.set_attribute("payment.intent_id", result["id"])
            span.set_attribute("payment.status",    result["status"])
            return result
        except stripe.StripeError as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            raise

stripe.PaymentIntent.create = _patched_pi_create
