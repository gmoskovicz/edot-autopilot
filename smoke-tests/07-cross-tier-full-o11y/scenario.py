#!/usr/bin/env python3
"""
Cross-Tier End-to-End Scenario: Mobile Service Activation
==========================================================

Demonstrates a single business transaction flowing through ALL FOUR tiers with:
  - Distributed tracing (one trace_id across all services)
  - Structured logs correlated to spans via trace.id
  - Metrics per service (counters, histograms)

The flow:
  Tier A: activation-api         ← REST gateway, validates customer request
  Tier B: legacy-billing-engine  ← checks credit limit in old billing system
  Tier C: payment-gateway-stripe ← charges first month (monkey-patched Stripe)
  Tier D: notification-sms-bash  ← sends SMS confirmation (via sidecar)

Three scenarios:
  1. Happy path         — full activation succeeds end-to-end
  2. Payment decline    — Tier C card decline, SMS sends "activation failed"
  3. SMS timeout        — Tier D non-fatal; activation succeeds, SMS degraded

Traceparent is threaded explicitly through each tier so Elastic APM
builds a connected service map with parent-child span relationships.

Run:
    cd smoke-tests
    # Start sidecar first (Tier D):
    OTEL_SERVICE_NAME=notification-sms-bash python3 ../otel-sidecar/otel-sidecar.py &
    python3 07-cross-tier-full-o11y/scenario.py
"""

import os, sys, uuid, time, random, json, urllib.request
from pathlib import Path

# Load .env
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap

from opentelemetry import trace, context
from opentelemetry.trace import SpanKind, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

ENDPOINT = os.environ["ELASTIC_OTLP_ENDPOINT"]
API_KEY  = os.environ["ELASTIC_API_KEY"]
ENV      = os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test")
SIDECAR  = os.environ.get("OTEL_SIDECAR_URL", "http://127.0.0.1:9411")

propagator = TraceContextTextMapPropagator()

# ── Per-service O11y bootstrap ────────────────────────────────────────────────
# Each service has its own provider → distinct node in Elastic service map

tier_a = O11yBootstrap("activation-api",        ENDPOINT, API_KEY, ENV)
tier_b = O11yBootstrap("legacy-billing-engine",  ENDPOINT, API_KEY, ENV)
tier_c = O11yBootstrap("payment-gateway-stripe", ENDPOINT, API_KEY, ENV)
# Tier D uses the sidecar — no SDK

# ── Metrics instruments ───────────────────────────────────────────────────────
# Tier A
a_activations    = tier_a.meter.create_counter("activation.requests",
                     description="Total activation requests received")
a_latency        = tier_a.meter.create_histogram("activation.duration_ms",
                     description="End-to-end activation latency", unit="ms")

# Tier B
b_credit_checks  = tier_b.meter.create_counter("billing.credit_checks",
                     description="Credit limit checks performed")
b_credit_latency = tier_b.meter.create_histogram("billing.credit_check_ms",
                     description="Credit check latency", unit="ms")

# Tier C
c_charges        = tier_c.meter.create_counter("stripe.charges",
                     description="Stripe charge attempts")
c_charge_value   = tier_c.meter.create_histogram("stripe.charge_usd",
                     description="Charge amounts", unit="USD")
c_charge_latency = tier_c.meter.create_histogram("stripe.charge_ms",
                     description="Stripe API latency", unit="ms")


# ── Sidecar helper (Tier D — plain HTTP, no SDK) ──────────────────────────────
def sidecar_post(payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(SIDECAR, data, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def sidecar_start(name, traceparent=None, **attrs):
    payload = {"action": "start_span", "name": name, "attributes": attrs}
    if traceparent:
        payload["traceparent"] = traceparent
    r = sidecar_post(payload)
    return r.get("span_id", ""), r.get("traceparent", "")


def sidecar_end(span_id, error=None, **attrs):
    if not span_id: return
    payload = {"action": "end_span", "span_id": span_id, "attributes": attrs}
    if error: payload["error"] = error
    sidecar_post(payload)


def sidecar_log(severity, message, traceparent=None, **attrs):
    payload = {"action": "log", "severity": severity, "body": message, "attributes": attrs}
    if traceparent:
        payload["traceparent"] = traceparent
    sidecar_post(payload)


def sidecar_counter(name, value=1, **attrs):
    sidecar_post({"action": "metric_counter", "name": name, "value": value, "attributes": attrs})


def sidecar_histogram(name, value, **attrs):
    sidecar_post({"action": "metric_histogram", "name": name, "value": value, "attributes": attrs})


# ── Traceparent extraction/injection helpers ──────────────────────────────────
def inject_traceparent(span) -> str:
    """Extract W3C traceparent string from a span context."""
    sc = span.get_span_context()
    return f"00-{sc.trace_id:032x}-{sc.span_id:016x}-01"


def extract_context(traceparent: str):
    """Build OTel context from a traceparent string."""
    return propagator.extract({"traceparent": traceparent})


# ── Check sidecar availability ────────────────────────────────────────────────
def sidecar_available() -> bool:
    r = sidecar_post({"action": "health"})
    return r.get("ok", False)


# ── Individual tier functions ─────────────────────────────────────────────────

def run_tier_a(customer: dict, scenario: str) -> tuple:
    """
    Tier A: activation-api
    Validates customer, starts the distributed trace.
    Returns (success, traceparent, activation_id).
    """
    activation_id = f"ACT-{uuid.uuid4().hex[:8].upper()}"
    t0 = time.time()

    with tier_a.tracer.start_as_current_span(
        "activation.request", kind=SpanKind.SERVER,
        attributes={
            "activation.id":        activation_id,
            "customer.id":          customer["id"],
            "customer.tier":        customer["tier"],
            "customer.plan":        customer["plan"],
            "http.method":          "POST",
            "http.route":           "/api/v1/activations",
            "scenario":             scenario,
        }
    ) as span:
        traceparent = inject_traceparent(span)

        # Validate customer
        tier_a.logger.info(
            f"activation request received for customer {customer['id']}",
            extra={"activation.id": activation_id, "customer.id": customer["id"],
                   "customer.tier": customer["tier"], "customer.plan": customer["plan"]},
        )

        # Simulate customer validation
        time.sleep(0.02)
        if customer.get("blocked"):
            span.set_status(StatusCode.ERROR, "Customer account suspended")
            tier_a.logger.error(
                "activation rejected: customer account suspended",
                extra={"activation.id": activation_id, "customer.id": customer["id"]},
            )
            a_activations.add(1, attributes={"result": "rejected", "customer.tier": customer["tier"]})
            return False, traceparent, activation_id

        span.set_attribute("activation.validation", "passed")
        tier_a.logger.info(
            "customer validation passed",
            extra={"activation.id": activation_id, "customer.id": customer["id"]},
        )
        return True, traceparent, activation_id


def run_tier_a_complete(activation_id, traceparent_from_a, success, scenario, customer, duration_ms):
    """Close the Tier A span after all downstream tiers complete."""
    parent_ctx = extract_context(traceparent_from_a)
    with tier_a.tracer.start_as_current_span(
        "activation.complete", kind=SpanKind.INTERNAL,
        context=parent_ctx,
        attributes={
            "activation.id":  activation_id,
            "activation.result": "success" if success else "failed",
            "scenario":       scenario,
        }
    ) as span:
        if not success:
            span.set_status(StatusCode.ERROR, "Activation failed")

        a_activations.add(1, attributes={"result": "success" if success else "failed",
                                          "customer.tier": customer["tier"]})
        a_latency.record(duration_ms, attributes={"result": "success" if success else "failed",
                                                    "scenario": scenario})

        tier_a.logger.info(
            f"activation {'completed' if success else 'failed'}: {activation_id}",
            extra={"activation.id": activation_id, "activation.result": "success" if success else "failed",
                   "activation.duration_ms": duration_ms},
        )


def run_tier_b(activation_id, customer, parent_traceparent) -> tuple:
    """
    Tier B: legacy-billing-engine
    Checks credit limit using manual span wrapping pattern.
    Returns (credit_ok, traceparent).
    """
    parent_ctx = extract_context(parent_traceparent)
    t0 = time.time()

    with tier_b.tracer.start_as_current_span(
        "billing.credit_check", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={
            "activation.id":    activation_id,
            "customer.id":      customer["id"],
            "customer.tier":    customer["tier"],
            "billing.system":   "legacy-v2-cobol",
            "billing.currency": "usd",
        }
    ) as span:
        traceparent = inject_traceparent(span)
        time.sleep(0.04)  # simulate legacy system latency

        # Legacy system lookup
        credit_limit = {"enterprise": 50000, "pro": 5000, "free": 100}.get(
            customer["tier"], 100
        )
        plan_cost = customer.get("plan_cost_usd", 29.99)
        credit_ok = credit_limit >= plan_cost

        span.set_attribute("billing.credit_limit_usd", credit_limit)
        span.set_attribute("billing.plan_cost_usd",    plan_cost)
        span.set_attribute("billing.credit_sufficient", credit_ok)

        dur_ms = (time.time() - t0) * 1000
        b_credit_checks.add(1, attributes={"result": "approved" if credit_ok else "denied",
                                            "customer.tier": customer["tier"]})
        b_credit_latency.record(dur_ms, attributes={"billing.system": "legacy-v2-cobol"})

        if credit_ok:
            tier_b.logger.info(
                f"credit check approved for {customer['id']}: limit=${credit_limit}",
                extra={"activation.id": activation_id, "customer.id": customer["id"],
                       "billing.credit_limit_usd": credit_limit,
                       "billing.plan_cost_usd": plan_cost},
            )
        else:
            span.set_status(StatusCode.ERROR, "Insufficient credit")
            tier_b.logger.warning(
                f"credit check denied: limit=${credit_limit} < cost=${plan_cost}",
                extra={"activation.id": activation_id, "customer.id": customer["id"],
                       "billing.credit_limit_usd": credit_limit,
                       "billing.plan_cost_usd": plan_cost},
            )

        return credit_ok, traceparent


def run_tier_c(activation_id, customer, parent_traceparent, force_decline=False) -> tuple:
    """
    Tier C: payment-gateway-stripe
    Charges first month using monkey-patch pattern.
    Returns (charge_ok, traceparent, charge_id).
    """
    parent_ctx = extract_context(parent_traceparent)
    amount_usd = customer.get("plan_cost_usd", 29.99)
    t0 = time.time()

    with tier_c.tracer.start_as_current_span(
        "stripe.charge.create", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={
            "activation.id":       activation_id,
            "payment.provider":    "stripe",
            "payment.amount_usd":  amount_usd,
            "payment.currency":    "usd",
            "payment.customer_id": customer["id"],
            "payment.description": f"Service activation — {customer['plan']} plan",
        }
    ) as span:
        traceparent = inject_traceparent(span)
        time.sleep(0.06)  # stripe API latency

        # Simulate decline for scenario 2
        if force_decline:
            charge_id = None
            span.set_status(StatusCode.ERROR, "card_declined: insufficient funds")
            span.set_attribute("payment.error_code", "card_declined")
            span.set_attribute("payment.status",     "failed")

            dur_ms = (time.time() - t0) * 1000
            c_charges.add(1,       attributes={"payment.status": "failed", "payment.currency": "usd"})
            c_charge_latency.record(dur_ms, attributes={"payment.status": "failed"})

            tier_c.logger.error(
                f"stripe charge failed: card_declined",
                extra={"activation.id": activation_id, "payment.amount_usd": amount_usd,
                       "payment.error_code": "card_declined", "payment.customer_id": customer["id"]},
            )
            return False, traceparent, None

        charge_id = f"ch_{uuid.uuid4().hex[:16]}"
        span.set_attribute("payment.charge_id", charge_id)
        span.set_attribute("payment.status",    "succeeded")
        span.set_attribute("payment.captured",  True)

        dur_ms = (time.time() - t0) * 1000
        c_charges.add(1,        attributes={"payment.status": "succeeded", "payment.currency": "usd"})
        c_charge_value.record(amount_usd, attributes={"payment.currency": "usd",
                                                       "customer.tier": customer["tier"]})
        c_charge_latency.record(dur_ms,   attributes={"payment.status": "succeeded"})

        tier_c.logger.info(
            f"stripe charge succeeded: {charge_id}",
            extra={"activation.id": activation_id, "payment.charge_id": charge_id,
                   "payment.amount_usd": amount_usd, "payment.customer_id": customer["id"]},
        )
        return True, traceparent, charge_id


def run_tier_d(activation_id, customer, parent_traceparent, sms_timeout=False) -> bool:
    """
    Tier D: notification-sms-bash (via sidecar)
    Sends SMS confirmation. Returns True if delivered.
    """
    sms_id, sms_tp = sidecar_start(
        "sms.send", parent_traceparent,
        **{
            "activation.id":    activation_id,
            "sms.recipient":    customer.get("phone", "+1-555-0100"),
            "sms.provider":     "twilio",
            "sms.type":         "activation_confirmation",
            "customer.id":      customer["id"],
        }
    )

    sidecar_log("INFO", f"SMS dispatch started for {customer['id']}", sms_tp,
                **{"activation.id": activation_id, "sms.recipient": customer.get("phone", "+1-555-0100")})

    time.sleep(0.03)

    if sms_timeout:
        sidecar_end(sms_id, error="Twilio timeout: no response after 3s",
                    **{"sms.status": "timeout", "sms.provider": "twilio",
                       "sms.retry_scheduled": True})
        sidecar_log("WARN", "SMS delivery timeout — queued for retry", sms_tp,
                    **{"activation.id": activation_id, "sms.status": "timeout",
                       "sms.retry_scheduled": "true"})
        sidecar_counter("sms.timeouts", 1, **{"sms.provider": "twilio"})
        sidecar_histogram("sms.dispatch_ms", 3000, **{"sms.status": "timeout"})
        return False

    sidecar_end(sms_id,
                **{"sms.status": "delivered", "sms.provider": "twilio",
                   "sms.message_sid": f"SM{uuid.uuid4().hex[:32]}"})
    sidecar_log("INFO", "SMS delivered successfully", sms_tp,
                **{"activation.id": activation_id, "sms.status": "delivered",
                   "customer.id": customer["id"]})
    sidecar_counter("sms.sent", 1, **{"sms.provider": "twilio", "sms.type": "activation_confirmation"})
    sidecar_histogram("sms.dispatch_ms", 30, **{"sms.status": "delivered"})
    return True


# ── Run scenarios ─────────────────────────────────────────────────────────────

def run_scenario(name: str, customer: dict, force_payment_decline=False, sms_timeout=False):
    print(f"\n  [{name}] customer={customer['id']} plan={customer['plan']} "
          f"tier={customer['tier']}")
    t_start = time.time()

    # Tier A: receive activation request
    ok, tp_a, activation_id = run_tier_a(customer, name)
    if not ok:
        print(f"    ❌ Tier A: customer blocked")
        return

    print(f"    ✅ Tier A (activation-api): request accepted — {activation_id}")

    # Tier B: credit check
    credit_ok, tp_b = run_tier_b(activation_id, customer, tp_a)
    if not credit_ok:
        print(f"    ❌ Tier B (legacy-billing-engine): credit check denied")
        run_tier_a_complete(activation_id, tp_a, False, name, customer,
                            (time.time() - t_start) * 1000)
        return
    print(f"    ✅ Tier B (legacy-billing-engine): credit approved")

    # Tier C: charge first month
    charge_ok, tp_c, charge_id = run_tier_c(activation_id, customer, tp_b,
                                             force_decline=force_payment_decline)
    if not charge_ok:
        print(f"    🚫 Tier C (payment-gateway-stripe): card declined")
        # Still send "activation failed" SMS via Tier D
        run_tier_d(activation_id, {**customer, "phone": "+1-555-0199"},
                   tp_c, sms_timeout=False)
        print(f"    📱 Tier D (notification-sms-bash): 'activation failed' SMS sent")
        run_tier_a_complete(activation_id, tp_a, False, name, customer,
                            (time.time() - t_start) * 1000)
        return
    print(f"    ✅ Tier C (payment-gateway-stripe): charge {charge_id}")

    # Tier D: send SMS
    sms_ok = run_tier_d(activation_id, customer, tp_c, sms_timeout=sms_timeout)
    if sms_ok:
        print(f"    ✅ Tier D (notification-sms-bash): confirmation SMS delivered")
    else:
        print(f"    ⚠️  Tier D (notification-sms-bash): SMS timeout — queued for retry")

    # Activation succeeds even if SMS times out (non-fatal)
    overall_success = True
    run_tier_a_complete(activation_id, tp_a, overall_success, name, customer,
                        (time.time() - t_start) * 1000)
    print(f"    ✅ Activation {activation_id} complete  "
          f"({int((time.time() - t_start)*1000)}ms end-to-end)")


# ── Main ──────────────────────────────────────────────────────────────────────

print(f"\n{'='*70}")
print(f"  Cross-Tier Full O11y — Mobile Service Activation")
print(f"  Tiers: A(activation-api) → B(legacy-billing-engine) → "
      f"C(payment-gateway-stripe) → D(notification-sms-bash)")
print(f"{'='*70}")

# Check sidecar
sidecar_ok = sidecar_available()
if not sidecar_ok:
    print("\n  ⚠️  Sidecar not available at {SIDECAR} — Tier D spans will be skipped")
    print("     Start with: OTEL_SERVICE_NAME=notification-sms-bash "
          "python3 otel-sidecar/otel-sidecar.py")
else:
    print(f"\n  ✅ Sidecar ready at {SIDECAR}")

customers = {
    "enterprise": {
        "id": f"CUST-ENT-{uuid.uuid4().hex[:6].upper()}",
        "tier": "enterprise", "plan": "enterprise-unlimited",
        "plan_cost_usd": 2999.00, "phone": "+1-800-555-0101",
    },
    "pro": {
        "id": f"CUST-PRO-{uuid.uuid4().hex[:6].upper()}",
        "tier": "pro", "plan": "pro-standard",
        "plan_cost_usd": 99.00, "phone": "+1-415-555-0102",
    },
    "free_decline": {
        "id": f"CUST-FREE-{uuid.uuid4().hex[:6].upper()}",
        "tier": "free", "plan": "free-starter",
        "plan_cost_usd": 0.0, "phone": "+1-650-555-0103",
    },
}

print(f"\n{'─'*70}")
print("  Scenario 1: Happy path — enterprise customer, full activation")
run_scenario("happy-path", customers["enterprise"])

print(f"\n{'─'*70}")
print("  Scenario 2: Payment decline — card refused at Tier C")
run_scenario("payment-decline", customers["pro"], force_payment_decline=True)

print(f"\n{'─'*70}")
print("  Scenario 3: SMS timeout — activation succeeds, SMS delivery degraded")
run_scenario("sms-timeout", customers["enterprise"], sms_timeout=True)

print(f"\n{'─'*70}")
print("  Flushing all providers...")

tier_a.flush()
tier_b.flush()
tier_c.flush()

print(f"\n{'='*70}")
print("  ✅ Cross-tier scenario complete")
print()
print("  Kibana Service Map:  Observability → APM → Service Map")
print("  Filter by: activation-api  (you'll see all 4 tiers connected)")
print()
print("  ES|QL — full trace including logs:")
print("    FROM traces-apm*,logs-*")
print("    | WHERE service.name IN (\"activation-api\", \"legacy-billing-engine\",")
print("                             \"payment-gateway-stripe\", \"notification-sms-bash\")")
print("    | SORT @timestamp DESC | LIMIT 50")
print(f"{'='*70}\n")
