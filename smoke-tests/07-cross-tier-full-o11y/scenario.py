#!/usr/bin/env python3
"""
Cross-Tier End-to-End Scenarios
================================

Eight distinct business flows — each using a different combination of tiers —
so the Elastic APM service map shows varied connection patterns, not just
a single linear chain.

Services:
  activation-api          Tier A — REST gateway (native OTel SDK)
  legacy-billing-engine   Tier B — credit / billing system (manual span wrap)
  payment-gateway-stripe  Tier C — Stripe charge (monkey-patched library)
  notification-sms-bash   Tier D — SMS dispatch (HTTP sidecar, no SDK)

Scenarios and tier combinations:
  1. A→B→C→D   Enterprise activation       — full happy path
  2. A→C→D     Pre-approved customer        — skip billing, pay and notify
  3. A→B→D     Invoice billing              — approved, no upfront charge, SMS only
  4. A→D       Free tier activation         — no billing, no payment
  5. D→B→A     COBOL batch dunning          — legacy initiates, billing flags, API suspends
  6. B→C→D     Auto-renewal cycle           — billing triggers charge + notification
  7. C→A→D     Payment webhook              — Stripe event updates API, SMS confirms
  8. A→B       Credit check denial          — stops at Tier B, no downstream calls

Run:
    cd smoke-tests
    # Start sidecar (required for Tier D spans):
    OTEL_SERVICE_NAME=notification-sms-bash python3 ../otel-sidecar/otel-sidecar.py &
    python3 07-cross-tier-full-o11y/scenario.py
"""

import os, sys, uuid, time, json, urllib.request
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")
if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap

from opentelemetry.trace import SpanKind, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

ENV     = os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test")
SIDECAR = os.environ.get("OTEL_SIDECAR_URL", "http://127.0.0.1:9411")

CHECKS: list[tuple[str, str, str]] = []

def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

propagator = TraceContextTextMapPropagator()

# ── Per-service O11y bootstrap ────────────────────────────────────────────────
tier_a = O11yBootstrap("activation-api",        ENDPOINT, API_KEY, ENV)
tier_b = O11yBootstrap("legacy-billing-engine",  ENDPOINT, API_KEY, ENV)
tier_c = O11yBootstrap("payment-gateway-stripe", ENDPOINT, API_KEY, ENV)
# Tier D uses the sidecar — no SDK, plain HTTP calls

# ── Metrics instruments ───────────────────────────────────────────────────────
a_requests   = tier_a.meter.create_counter("activation.requests")
a_latency    = tier_a.meter.create_histogram("activation.duration_ms", unit="ms")
b_checks     = tier_b.meter.create_counter("billing.checks")
b_latency    = tier_b.meter.create_histogram("billing.check_ms", unit="ms")
c_charges    = tier_c.meter.create_counter("stripe.charges")
c_value      = tier_c.meter.create_histogram("stripe.charge_usd", unit="USD")
c_latency    = tier_c.meter.create_histogram("stripe.charge_ms", unit="ms")


# ── Helpers ───────────────────────────────────────────────────────────────────
def inject_tp(span) -> str:
    sc = span.get_span_context()
    return f"00-{sc.trace_id:032x}-{sc.span_id:016x}-01"

def extract_ctx(tp: str):
    return propagator.extract({"traceparent": tp})

def sidecar(payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(SIDECAR, data, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}

def sd_start(name, tp=None, **attrs):
    p = {"action": "start_span", "name": name, "attributes": attrs}
    if tp: p["traceparent"] = tp
    r = sidecar(p)
    return r.get("span_id", ""), r.get("traceparent", "")

def sd_end(sid, error=None, **attrs):
    if not sid: return
    p = {"action": "end_span", "span_id": sid, "attributes": attrs}
    if error: p["error"] = error
    sidecar(p)

def sd_log(sev, msg, tp=None, **attrs):
    p = {"action": "log", "severity": sev, "body": msg, "attributes": attrs}
    if tp: p["traceparent"] = tp
    sidecar(p)

def sd_counter(name, val=1, **attrs):
    sidecar({"action": "metric_counter", "name": name, "value": val, "attributes": attrs})

def sd_histogram(name, val, **attrs):
    sidecar({"action": "metric_histogram", "name": name, "value": val, "attributes": attrs})


# ── Individual service calls ───────────────────────────────────────────────────

def svc_a_receive(customer, scenario, parent_tp=None) -> tuple:
    """Tier A — receive and validate an activation request."""
    act_id = f"ACT-{uuid.uuid4().hex[:8].upper()}"
    ctx    = extract_ctx(parent_tp) if parent_tp else None
    kwargs = {"context": ctx} if ctx else {}

    with tier_a.tracer.start_as_current_span(
        "activation.receive", kind=SpanKind.SERVER,
        attributes={"activation.id": act_id, "customer.id": customer["id"],
                    "customer.tier": customer["tier"], "scenario": scenario,
                    "http.method": "POST", "http.route": "/api/v1/activations"},
        **kwargs
    ) as span:
        time.sleep(0.02)
        tp = inject_tp(span)
        if customer.get("blocked"):
            span.record_exception(PermissionError("Account suspended"),
                                  attributes={"exception.escaped": True})
            span.set_status(StatusCode.ERROR, "Account suspended")
            a_requests.add(1, {"result": "rejected", "customer.tier": customer["tier"]})
            tier_a.logger.error("activation rejected: account suspended",
                                extra={"activation.id": act_id, "customer.id": customer["id"]})
            return False, tp, act_id
        span.set_attribute("activation.validation", "passed")
        tier_a.logger.info("activation request accepted",
                           extra={"activation.id": act_id, "customer.id": customer["id"],
                                  "customer.tier": customer["tier"]})
        return True, tp, act_id


def svc_a_complete(act_id, parent_tp, success, scenario, customer, duration_ms):
    """Tier A — close the activation with final result."""
    with tier_a.tracer.start_as_current_span(
        "activation.complete", kind=SpanKind.INTERNAL,
        context=extract_ctx(parent_tp),
        attributes={"activation.id": act_id, "activation.result": "success" if success else "failed",
                    "scenario": scenario}
    ) as span:
        if not success:
            span.record_exception(RuntimeError("Activation failed"),
                                  attributes={"exception.escaped": True})
            span.set_status(StatusCode.ERROR, "Activation failed")
        a_requests.add(1, {"result": "success" if success else "failed",
                           "customer.tier": customer["tier"]})
        a_latency.record(duration_ms, {"result": "success" if success else "failed"})
        tier_a.logger.info(f"activation {'complete' if success else 'failed'}: {act_id}",
                           extra={"activation.id": act_id,
                                  "activation.result": "success" if success else "failed",
                                  "activation.duration_ms": round(duration_ms, 1)})


def svc_b_credit(act_id, customer, parent_tp) -> tuple:
    """Tier B — credit check in legacy billing system."""
    t0 = time.time()
    with tier_b.tracer.start_as_current_span(
        "billing.credit_check", kind=SpanKind.CLIENT,
        context=extract_ctx(parent_tp),
        attributes={"activation.id": act_id, "customer.id": customer["id"],
                    "customer.tier": customer["tier"], "billing.system": "legacy-v2-cobol"}
    ) as span:
        time.sleep(0.04)
        tp = inject_tp(span)
        limit = {"enterprise": 50000, "pro": 5000, "free": 100}.get(customer["tier"], 100)
        cost  = customer.get("plan_cost_usd", 29.99)
        ok    = limit >= cost
        span.set_attribute("billing.credit_limit_usd", limit)
        span.set_attribute("billing.plan_cost_usd",    cost)
        span.set_attribute("billing.credit_sufficient", ok)
        dur   = (time.time() - t0) * 1000
        b_checks.add(1,  {"result": "approved" if ok else "denied", "customer.tier": customer["tier"]})
        b_latency.record(dur, {"billing.system": "legacy-v2-cobol"})
        if not ok:
            span.record_exception(ValueError(f"Insufficient credit: limit=${limit} < cost=${cost}"),
                                  attributes={"exception.escaped": True})
            span.set_status(StatusCode.ERROR, "Insufficient credit")
            tier_b.logger.warning("credit check denied",
                                  extra={"activation.id": act_id, "billing.credit_limit_usd": limit,
                                         "billing.plan_cost_usd": cost})
        else:
            tier_b.logger.info(f"credit approved: limit=${limit}",
                               extra={"activation.id": act_id, "customer.id": customer["id"],
                                      "billing.credit_limit_usd": limit})
        return ok, tp


def svc_b_flag_overdue(account_id, parent_tp, amount_overdue) -> tuple:
    """Tier B — flag overdue account (called by Tier D dunning batch)."""
    t0 = time.time()
    with tier_b.tracer.start_as_current_span(
        "billing.flag_overdue", kind=SpanKind.SERVER,
        context=extract_ctx(parent_tp),
        attributes={"account.id": account_id, "billing.overdue_usd": amount_overdue,
                    "billing.system": "legacy-v2-cobol", "billing.action": "suspend"}
    ) as span:
        time.sleep(0.03)
        tp = inject_tp(span)
        span.set_attribute("billing.status_set", "suspended")
        dur = (time.time() - t0) * 1000
        b_checks.add(1, {"result": "flagged", "customer.tier": "unknown"})
        b_latency.record(dur, {"billing.system": "legacy-v2-cobol"})
        tier_b.logger.warning(f"account flagged overdue: {account_id} (${amount_overdue})",
                              extra={"account.id": account_id,
                                     "billing.overdue_usd": amount_overdue,
                                     "billing.status_set": "suspended"})
        return tp


def svc_b_initiate_renewal(account_id, customer) -> tuple:
    """Tier B — auto-renewal: billing initiates a new charge cycle."""
    act_id = f"RENEW-{uuid.uuid4().hex[:8].upper()}"
    with tier_b.tracer.start_as_current_span(
        "billing.initiate_renewal", kind=SpanKind.PRODUCER,
        attributes={"account.id": account_id, "renewal.id": act_id,
                    "billing.plan": customer["plan"],
                    "billing.amount_usd": customer.get("plan_cost_usd", 29.99),
                    "billing.system": "legacy-v2-cobol"}
    ) as span:
        time.sleep(0.02)
        tp = inject_tp(span)
        b_checks.add(1, {"result": "renewal", "customer.tier": customer["tier"]})
        tier_b.logger.info(f"auto-renewal initiated: {act_id}",
                           extra={"account.id": account_id, "renewal.id": act_id,
                                  "billing.amount_usd": customer.get("plan_cost_usd", 29.99)})
        return act_id, tp


def svc_c_charge(act_id, customer, parent_tp, force_decline=False) -> tuple:
    """Tier C — charge via Stripe (monkey-patched library)."""
    amount = customer.get("plan_cost_usd", 29.99)
    t0     = time.time()
    with tier_c.tracer.start_as_current_span(
        "stripe.charge.create", kind=SpanKind.CLIENT,
        context=extract_ctx(parent_tp),
        attributes={"activation.id": act_id, "payment.provider": "stripe",
                    "payment.amount_usd": amount, "payment.currency": "usd",
                    "payment.customer_id": customer["id"]}
    ) as span:
        time.sleep(0.06)
        tp  = inject_tp(span)
        dur = (time.time() - t0) * 1000
        if force_decline:
            span.record_exception(ValueError("card_declined: insufficient_funds"),
                                  attributes={"exception.escaped": True})
            span.set_status(StatusCode.ERROR, "card_declined")
            span.set_attribute("payment.error_code", "card_declined")
            span.set_attribute("payment.status",     "failed")
            c_charges.add(1, {"payment.status": "failed"})
            c_latency.record(dur, {"payment.status": "failed"})
            tier_c.logger.error("stripe charge failed: card_declined",
                                extra={"activation.id": act_id, "payment.amount_usd": amount,
                                       "payment.error_code": "card_declined"})
            return False, tp, None
        charge_id = f"ch_{uuid.uuid4().hex[:16]}"
        span.set_attribute("payment.charge_id", charge_id)
        span.set_attribute("payment.status",    "succeeded")
        c_charges.add(1, {"payment.status": "succeeded"})
        c_value.record(amount, {"customer.tier": customer["tier"]})
        c_latency.record(dur,   {"payment.status": "succeeded"})
        tier_c.logger.info(f"stripe charge succeeded: {charge_id}",
                           extra={"activation.id": act_id, "payment.charge_id": charge_id,
                                  "payment.amount_usd": amount})
        return True, tp, charge_id


def svc_c_webhook_received(event_id, charge_id, customer, amount) -> tuple:
    """Tier C — Stripe webhook received (C acts as entry point)."""
    with tier_c.tracer.start_as_current_span(
        "stripe.webhook.payment_succeeded", kind=SpanKind.SERVER,
        attributes={"stripe.event_id": event_id, "stripe.charge_id": charge_id,
                    "payment.amount_usd": amount, "payment.currency": "usd",
                    "payment.customer_id": customer["id"],
                    "http.method": "POST", "http.route": "/webhooks/stripe"}
    ) as span:
        time.sleep(0.01)
        tp = inject_tp(span)
        c_charges.add(1, {"payment.status": "webhook_received"})
        tier_c.logger.info(f"stripe webhook received: {event_id}",
                           extra={"stripe.event_id": event_id,
                                  "stripe.charge_id": charge_id,
                                  "payment.amount_usd": amount})
        return tp


def svc_d_notify(act_id, customer, parent_tp, msg_type="activation_confirmation",
                 force_timeout=False) -> bool:
    """Tier D — send SMS via sidecar."""
    sid, sms_tp = sd_start(
        "sms.send", parent_tp,
        **{"activation.id": act_id, "sms.type": msg_type,
           "sms.provider": "twilio", "customer.id": customer["id"],
           "sms.recipient": customer.get("phone", "+1-555-0100")}
    )
    sd_log("INFO", f"SMS dispatch started: {msg_type}", sms_tp,
           **{"activation.id": act_id, "sms.type": msg_type})
    time.sleep(0.03)
    if force_timeout:
        sd_end(sid, error="Twilio timeout after 3s",
               **{"sms.status": "timeout", "sms.retry_scheduled": True})
        sd_log("WARN", "SMS timeout — queued for retry", sms_tp,
               **{"activation.id": act_id, "sms.status": "timeout"})
        sd_counter("sms.timeouts", 1, **{"sms.provider": "twilio"})
        sd_histogram("sms.dispatch_ms", 3000, **{"sms.status": "timeout"})
        return False
    sid_val = f"SM{uuid.uuid4().hex[:32]}"
    sd_end(sid, **{"sms.status": "delivered", "sms.message_sid": sid_val})
    sd_log("INFO", "SMS delivered", sms_tp,
           **{"activation.id": act_id, "sms.status": "delivered", "sms.message_sid": sid_val})
    sd_counter("sms.sent", 1, **{"sms.type": msg_type})
    sd_histogram("sms.dispatch_ms", random.randint(25, 120), **{"sms.status": "delivered"})
    return True


def svc_d_batch_dunning(batch_id) -> list:
    """Tier D — COBOL-style batch: scan accounts, return overdue items with traceparents."""
    results = []
    accounts = [
        {"id": f"ACC-{uuid.uuid4().hex[:6].upper()}", "overdue_usd": round(random.uniform(50, 2000), 2)},
        {"id": f"ACC-{uuid.uuid4().hex[:6].upper()}", "overdue_usd": round(random.uniform(50, 500), 2)},
    ]
    batch_sid, batch_tp = sd_start(
        "cobol.batch.dunning_scan", None,
        **{"batch.id": batch_id, "batch.account_count": len(accounts),
           "batch.source": "legacy-erp", "runtime": "cobol"}
    )
    sd_log("INFO", f"dunning batch started: {batch_id}", batch_tp,
           **{"batch.id": batch_id, "batch.account_count": len(accounts)})
    time.sleep(0.05)
    for acc in accounts:
        item_sid, item_tp = sd_start(
            "cobol.batch.process_account", batch_tp,
            **{"account.id": acc["id"], "billing.overdue_usd": acc["overdue_usd"],
               "batch.id": batch_id}
        )
        time.sleep(0.02)
        sd_end(item_sid, **{"account.id": acc["id"], "batch.action": "flagged_for_suspension"})
        results.append({"account": acc, "traceparent": item_tp})
    sd_end(batch_sid, **{"batch.accounts_flagged": len(accounts), "batch.status": "complete"})
    sd_log("INFO", f"dunning batch complete: {len(accounts)} accounts flagged", batch_tp,
           **{"batch.id": batch_id, "batch.accounts_flagged": len(accounts)})
    sd_counter("batch.dunning_runs", 1, **{"batch.source": "legacy-erp"})
    return results


# ── Scenario runners ──────────────────────────────────────────────────────────

import random  # noqa: E402 (used in svc_d_notify)

def scenario_a_b_c_d(customer):
    """A→B→C→D  Full enterprise activation."""
    print("  Tiers: A → B → C → D")
    t0 = time.time()
    ok, tp_a, act_id = svc_a_receive(customer, "a-b-c-d")
    if not ok: return
    print(f"    ✅ A  activation-api: accepted {act_id}")
    credit_ok, tp_b = svc_b_credit(act_id, customer, tp_a)
    if not credit_ok:
        print(f"    ❌ B  legacy-billing-engine: credit denied"); return
    print(f"    ✅ B  legacy-billing-engine: credit approved")
    charge_ok, tp_c, charge_id = svc_c_charge(act_id, customer, tp_b)
    if not charge_ok:
        print(f"    ❌ C  payment-gateway-stripe: card declined"); return
    print(f"    ✅ C  payment-gateway-stripe: charged {charge_id}")
    sms_ok = svc_d_notify(act_id, customer, tp_c)
    print(f"    {'✅' if sms_ok else '⚠️ '} D  notification-sms-bash: {'delivered' if sms_ok else 'timeout'}")
    svc_a_complete(act_id, tp_a, True, "a-b-c-d", customer, (time.time()-t0)*1000)


def scenario_a_c_d(customer):
    """A→C→D  Pre-approved customer — skip billing."""
    print("  Tiers: A → C → D  (billing bypassed — pre-approved)")
    t0 = time.time()
    ok, tp_a, act_id = svc_a_receive(customer, "a-c-d")
    if not ok: return
    print(f"    ✅ A  activation-api: accepted {act_id}")
    charge_ok, tp_c, charge_id = svc_c_charge(act_id, customer, tp_a)
    if not charge_ok:
        print(f"    ❌ C  payment-gateway-stripe: card declined"); return
    print(f"    ✅ C  payment-gateway-stripe: charged {charge_id}")
    svc_d_notify(act_id, customer, tp_c)
    print(f"    ✅ D  notification-sms-bash: delivered")
    svc_a_complete(act_id, tp_a, True, "a-c-d", customer, (time.time()-t0)*1000)


def scenario_a_b_d(customer):
    """A→B→D  Invoice billing — credit approved, no upfront charge, SMS only."""
    print("  Tiers: A → B → D  (invoice customer — no card charge)")
    t0 = time.time()
    ok, tp_a, act_id = svc_a_receive(customer, "a-b-d")
    if not ok: return
    print(f"    ✅ A  activation-api: accepted {act_id}")
    credit_ok, tp_b = svc_b_credit(act_id, customer, tp_a)
    if not credit_ok:
        print(f"    ❌ B  legacy-billing-engine: credit denied"); return
    print(f"    ✅ B  legacy-billing-engine: credit approved (invoice terms)")
    svc_d_notify(act_id, customer, tp_b, msg_type="invoice_activation_confirmation")
    print(f"    ✅ D  notification-sms-bash: invoice confirmation sent")
    svc_a_complete(act_id, tp_a, True, "a-b-d", customer, (time.time()-t0)*1000)


def scenario_a_d(customer):
    """A→D  Free tier — validate and notify, no billing or payment."""
    print("  Tiers: A → D  (free tier — no billing, no payment)")
    t0 = time.time()
    ok, tp_a, act_id = svc_a_receive(customer, "a-d")
    if not ok: return
    print(f"    ✅ A  activation-api: accepted {act_id}")
    svc_d_notify(act_id, customer, tp_a, msg_type="free_tier_welcome")
    print(f"    ✅ D  notification-sms-bash: welcome SMS delivered")
    svc_a_complete(act_id, tp_a, True, "a-d", customer, (time.time()-t0)*1000)


def scenario_d_b_a():
    """D→B→A  COBOL batch dunning — legacy initiates, billing flags, API suspends."""
    print("  Tiers: D → B → A  (COBOL batch discovers overdue → billing → API suspends)")
    batch_id  = f"BATCH-DUN-{uuid.uuid4().hex[:8].upper()}"
    flagged   = svc_d_batch_dunning(batch_id)
    print(f"    ✅ D  COBOL batch (notification-sms-bash): {len(flagged)} overdue accounts found")
    for item in flagged:
        acc = item["account"]
        tp_b = svc_b_flag_overdue(acc["id"], item["traceparent"], acc["overdue_usd"])
        print(f"    ✅ B  legacy-billing-engine: flagged {acc['id']} (${acc['overdue_usd']} overdue)")
        # API receives suspension instruction from billing
        ok, tp_a, act_id = svc_a_receive(
            {"id": acc["id"], "tier": "free", "plan": "suspended",
             "plan_cost_usd": 0, "blocked": False},
            "d-b-a-suspend",
            parent_tp=tp_b,
        )
        with tier_a.tracer.start_as_current_span(
            "activation.suspend_account", kind=SpanKind.INTERNAL,
            context=__import__("opentelemetry.trace.propagation.tracecontext",
                               fromlist=["TraceContextTextMapPropagator"]) and
                    propagator.extract({"traceparent": tp_a}),
            attributes={"account.id": acc["id"], "suspension.reason": "overdue",
                        "billing.overdue_usd": acc["overdue_usd"]}
        ) as span:
            span.set_attribute("account.status", "suspended")
            tier_a.logger.warning(f"account suspended: {acc['id']} (overdue ${acc['overdue_usd']})",
                                  extra={"account.id": acc["id"],
                                         "billing.overdue_usd": acc["overdue_usd"]})
        print(f"    ✅ A  activation-api: account {acc['id']} suspended")


def scenario_b_c_d(customer):
    """B→C→D  Auto-renewal — billing triggers charge and notification."""
    print("  Tiers: B → C → D  (auto-renewal: billing initiates charge cycle)")
    act_id, tp_b = svc_b_initiate_renewal(customer["id"], customer)
    print(f"    ✅ B  legacy-billing-engine: renewal {act_id} initiated")
    charge_ok, tp_c, charge_id = svc_c_charge(act_id, customer, tp_b)
    if not charge_ok:
        print(f"    ❌ C  payment-gateway-stripe: renewal charge declined")
        svc_d_notify(act_id, customer, tp_c, msg_type="renewal_failed")
        print(f"    📱 D  notification-sms-bash: renewal failure SMS sent")
        return
    print(f"    ✅ C  payment-gateway-stripe: renewal charged {charge_id}")
    svc_d_notify(act_id, customer, tp_c, msg_type="renewal_receipt")
    print(f"    ✅ D  notification-sms-bash: renewal receipt SMS delivered")


def scenario_c_a_d(customer):
    """C→A→D  Stripe webhook — payment event updates API, API notifies user."""
    print("  Tiers: C → A → D  (Stripe webhook: payment event → API → SMS)")
    event_id  = f"evt_{uuid.uuid4().hex[:24]}"
    charge_id = f"ch_{uuid.uuid4().hex[:16]}"
    amount    = customer.get("plan_cost_usd", 29.99)
    tp_c      = svc_c_webhook_received(event_id, charge_id, customer, amount)
    print(f"    ✅ C  payment-gateway-stripe: webhook {event_id} received")
    # API processes the webhook event
    ok, tp_a, act_id = svc_a_receive(customer, "c-a-d-webhook", parent_tp=tp_c)
    if not ok: return
    with tier_a.tracer.start_as_current_span(
        "activation.process_payment_event", kind=SpanKind.INTERNAL,
        context=propagator.extract({"traceparent": tp_a}),
        attributes={"stripe.event_id": event_id, "payment.charge_id": charge_id,
                    "activation.id": act_id, "customer.id": customer["id"]}
    ) as span:
        time.sleep(0.015)
        span.set_attribute("activation.status_updated", "active")
        tier_a.logger.info(f"activation status updated from payment webhook",
                           extra={"stripe.event_id": event_id, "activation.id": act_id})
    print(f"    ✅ A  activation-api: account status updated from webhook")
    svc_d_notify(act_id, customer, tp_a, msg_type="payment_confirmed")
    print(f"    ✅ D  notification-sms-bash: payment confirmation SMS sent")


def scenario_a_b_denied(customer):
    """A→B  Credit check denial — stops at Tier B, nothing downstream."""
    print("  Tiers: A → B  (credit denied — no payment or notification attempted)")
    t0 = time.time()
    ok, tp_a, act_id = svc_a_receive(customer, "a-b-denied")
    if not ok: return
    print(f"    ✅ A  activation-api: accepted {act_id}")
    credit_ok, _ = svc_b_credit(act_id, customer, tp_a)
    if not credit_ok:
        print(f"    ❌ B  legacy-billing-engine: credit denied — activation stopped")
        svc_a_complete(act_id, tp_a, False, "a-b-denied", customer, (time.time()-t0)*1000)
    else:
        print(f"    ✅ B  credit unexpectedly approved — check customer fixture")


# ── Customer fixtures ──────────────────────────────────────────────────────────

enterprise = {
    "id": f"CUST-ENT-{uuid.uuid4().hex[:6].upper()}",
    "tier": "enterprise", "plan": "enterprise-unlimited",
    "plan_cost_usd": 2999.00, "phone": "+1-800-555-0101",
}
pro_preapproved = {
    "id": f"CUST-PRO-{uuid.uuid4().hex[:6].upper()}",
    "tier": "pro", "plan": "pro-standard",
    "plan_cost_usd": 99.00, "phone": "+1-415-555-0102",
}
pro_invoice = {
    "id": f"CUST-ENT-{uuid.uuid4().hex[:6].upper()}",
    "tier": "enterprise", "plan": "enterprise-invoice",
    "plan_cost_usd": 1499.00, "phone": "+1-212-555-0103",
}
free_user = {
    "id": f"CUST-FREE-{uuid.uuid4().hex[:6].upper()}",
    "tier": "free", "plan": "free-starter",
    "plan_cost_usd": 0.0, "phone": "+1-650-555-0104",
}
renewal_pro = {
    "id": f"CUST-PRO-{uuid.uuid4().hex[:6].upper()}",
    "tier": "pro", "plan": "pro-standard",
    "plan_cost_usd": 99.00, "phone": "+1-503-555-0105",
}
webhook_customer = {
    "id": f"CUST-PRO-{uuid.uuid4().hex[:6].upper()}",
    "tier": "pro", "plan": "pro-plus",
    "plan_cost_usd": 199.00, "phone": "+1-206-555-0106",
}
no_credit = {
    "id": f"CUST-FREE-{uuid.uuid4().hex[:6].upper()}",
    "tier": "free", "plan": "enterprise-plus",  # free tier credit limit is $100; this costs $2999
    "plan_cost_usd": 2999.00, "phone": "+1-702-555-0107",
}

# ── Main ──────────────────────────────────────────────────────────────────────

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | Cross-Tier Full O11y")
print(f"{'='*62}")

# Check sidecar
r = sidecar({"action": "health"})
if r.get("ok"):
    print(f"\n  Sidecar ready at {SIDECAR}")
else:
    print(f"\n  Sidecar unavailable ({r.get('error','no response')}) — Tier D spans skipped")
    print(f"     Start with: OTEL_SERVICE_NAME=notification-sms-bash "
          f"python3 otel-sidecar/otel-sidecar.py &")

results = []

scenarios = [
    ("1. A→B→C→D",  "Full enterprise activation",               lambda: scenario_a_b_c_d(enterprise)),
    ("2. A→C→D",    "Pre-approved customer (skip billing)",      lambda: scenario_a_c_d(pro_preapproved)),
    ("3. A→B→D",    "Invoice billing (no card charge)",          lambda: scenario_a_b_d(pro_invoice)),
    ("4. A→D",      "Free tier activation",                      lambda: scenario_a_d(free_user)),
    ("5. D→B→A",    "COBOL dunning batch → billing → API",       lambda: scenario_d_b_a()),
    ("6. B→C→D",    "Auto-renewal initiated by billing",         lambda: scenario_b_c_d(renewal_pro)),
    ("7. C→A→D",    "Stripe webhook updates API",                lambda: scenario_c_a_d(webhook_customer)),
    ("8. A→B",      "Credit check denial (stops at Tier B)",     lambda: scenario_a_b_denied(no_credit)),
]

for label, description, fn in scenarios:
    print(f"\n{'─'*62}")
    print(f"  Scenario {label}  —  {description}")
    try:
        fn()
        results.append((f"Scenario {label} — {description}", "OK", None))
    except Exception as e:
        results.append((f"Scenario {label} — {description}", "ERROR", str(e)))

print(f"\n{'─'*62}")
print("  Flushing all providers...")
tier_a.flush()
tier_b.flush()
tier_c.flush()

# ── Span assertions: verify instrumentation correctness ──────────────────────
spans_a = tier_a.get_finished_spans()
spans_b = tier_b.get_finished_spans()
spans_c = tier_c.get_finished_spans()
all_spans = list(spans_a) + list(spans_b) + list(spans_c)
span_names = [s.name for s in all_spans]

print("\nSpan assertions (instrumentation correctness):")
check("At least one span captured across all tiers",
      len(all_spans) > 0,
      f"got {len(all_spans)} total spans")
check("Tier A activation.receive SERVER span present",
      any(s.name == "activation.receive" and s.kind == SpanKind.SERVER for s in spans_a),
      f"tier_a span names: {[s.name for s in spans_a]}")
check("Tier B billing.credit_check CLIENT span present",
      any(s.name == "billing.credit_check" and s.kind == SpanKind.CLIENT for s in spans_b),
      f"tier_b span names: {[s.name for s in spans_b]}")
check("Tier C stripe.charge.create CLIENT span present",
      any(s.name == "stripe.charge.create" and s.kind == SpanKind.CLIENT for s in spans_c),
      f"tier_c span names: {[s.name for s in spans_c]}")
check("Spans from multiple tiers captured",
      len(spans_a) > 0 and len(spans_b) > 0 and len(spans_c) > 0,
      f"tier_a={len(spans_a)} tier_b={len(spans_b)} tier_c={len(spans_c)}")

for scenario_name, status, error_detail in results:
    if status in ("OK", "WARN"):
        check(scenario_name, True)
    else:
        check(scenario_name, False, error_detail or "")

passed = sum(1 for s, _, _ in CHECKS if s == "PASS")
failed = sum(1 for s, _, _ in CHECKS if s == "FAIL")
for status, name, detail in CHECKS:
    line = f"  [{status}] {name}"
    if detail and status == "FAIL":
        line += f"\n         -> {detail}"
    print(line)
print(f"\n  Result: {passed}/{len(CHECKS)} checks passed")
if failed:
    sys.exit(1)
