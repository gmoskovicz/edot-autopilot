#!/usr/bin/env python3
"""
E-Commerce Checkout Platform — Distributed Tracing Scenario
============================================================

Services modeled:
  checkout-frontend   → product-catalog
                      → inventory-service
                      → pricing-engine
                      → payment-service → fraud-detection
                                        → payment-processor (Stripe)
                      → order-service   → notification-service

30 trace scenarios with realistic error mix:
  60% happy path
  15% fraud block (score > 0.85)
  10% card declined
   8% inventory out of stock
   5% pricing engine timeout
   2% catastrophic DB failure in order-service

Run:
    cd smoke-tests
    python3 60-ecommerce/scenario.py
"""

import os, sys, uuid, time, random, threading
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

from opentelemetry.trace import SpanKind, StatusCode, Link
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry import baggage
from opentelemetry.baggage.propagation import W3CBaggagePropagator

ENV = os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test")

CHECKS: list[tuple[str, str, str]] = []

def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

propagator = TraceContextTextMapPropagator()

# ── Per-service O11y bootstrap ────────────────────────────────────────────────
checkout  = O11yBootstrap("checkout-frontend",   ENDPOINT, API_KEY, ENV)
catalog   = O11yBootstrap("product-catalog",     ENDPOINT, API_KEY, ENV)
inventory = O11yBootstrap("inventory-service",   ENDPOINT, API_KEY, ENV)
pricing   = O11yBootstrap("pricing-engine",      ENDPOINT, API_KEY, ENV)
payment   = O11yBootstrap("payment-service",     ENDPOINT, API_KEY, ENV)
fraud     = O11yBootstrap("fraud-detection",     ENDPOINT, API_KEY, ENV)
processor = O11yBootstrap("payment-processor",   ENDPOINT, API_KEY, ENV)
orders    = O11yBootstrap("order-service",       ENDPOINT, API_KEY, ENV)
notify    = O11yBootstrap("notification-service", ENDPOINT, API_KEY, ENV)

# ── Metrics instruments ───────────────────────────────────────────────────────
# checkout-frontend
co_requests    = checkout.meter.create_counter("checkout.requests",      description="Total checkout requests")
co_latency     = checkout.meter.create_histogram("checkout.duration_ms", description="End-to-end checkout latency", unit="ms")
co_value       = checkout.meter.create_histogram("checkout.order_value_usd", description="Order value", unit="USD")
co_errors      = checkout.meter.create_counter("checkout.errors",        description="Checkout errors by type")

# product-catalog
cat_lookups    = catalog.meter.create_counter("catalog.lookups",         description="Product lookup count")
cat_latency    = catalog.meter.create_histogram("catalog.lookup_ms",     description="Catalog lookup latency", unit="ms")

# inventory-service
inv_checks     = inventory.meter.create_counter("inventory.checks",      description="Stock check count")
inv_stockouts  = inventory.meter.create_counter("inventory.stockouts",   description="Out-of-stock events")

# pricing-engine
price_calcs    = pricing.meter.create_counter("pricing.calculations",    description="Price calc requests")
price_timeouts = pricing.meter.create_counter("pricing.timeouts",        description="Pricing timeout count")

# payment-service
pay_attempts   = payment.meter.create_counter("payment.attempts",        description="Payment attempts")
pay_value      = payment.meter.create_histogram("payment.amount_usd",    description="Payment amounts", unit="USD")
pay_latency    = payment.meter.create_histogram("payment.duration_ms",   description="Payment duration", unit="ms")

# fraud-detection
fraud_checks   = fraud.meter.create_counter("fraud.checks",              description="Fraud checks performed")
fraud_blocks   = fraud.meter.create_counter("fraud.blocks",              description="Fraud blocks")
fraud_scores   = fraud.meter.create_histogram("fraud.score",             description="Fraud score distribution")

# order-service
order_created  = orders.meter.create_counter("order.created",            description="Orders created")
order_errors   = orders.meter.create_counter("order.errors",             description="Order creation errors")

# notification-service
notif_sent     = notify.meter.create_counter("notification.sent",        description="Notifications sent")
notif_latency  = notify.meter.create_histogram("notification.duration_ms", description="Notification latency", unit="ms")

# ── Observable gauges ─────────────────────────────────────────────────────────
_active_checkouts = 0
_active_checkouts_lock = threading.Lock()

def _checkout_active_callback(options):
    from opentelemetry.metrics import Observation
    with _active_checkouts_lock:
        yield Observation(_active_checkouts, {"env": ENV})

def _fraud_cache_callback(options):
    from opentelemetry.metrics import Observation
    yield Observation(random.uniform(0.75, 0.95), {"model": "xgb-v4.1"})

def _payment_pool_callback(options):
    from opentelemetry.metrics import Observation
    yield Observation(random.randint(3, 10), {"processor": "stripe"})

checkout.meter.create_observable_gauge(
    "checkout.active_sessions", [_checkout_active_callback],
    description="Currently active checkout sessions"
)
fraud.meter.create_observable_gauge(
    "fraud.model_cache_hit_ratio", [_fraud_cache_callback],
    description="Fraud model feature cache hit ratio"
)
processor.meter.create_observable_gauge(
    "payment.connection_pool_size", [_payment_pool_callback],
    description="Active payment processor connections"
)


# ── Product catalog ────────────────────────────────────────────────────────────
PRODUCTS = [
    {"sku": "ELEC-001", "name": "Sony 4K OLED TV 65\"",        "category": "electronics",  "price": 1299.99, "weight_kg": 28.5},
    {"sku": "ELEC-002", "name": "Apple MacBook Pro M3",         "category": "electronics",  "price": 2499.00, "weight_kg": 2.1},
    {"sku": "ELEC-003", "name": "Samsung Galaxy S24 Ultra",     "category": "electronics",  "price": 1199.00, "weight_kg": 0.23},
    {"sku": "ELEC-004", "name": "Bose QC45 Headphones",         "category": "electronics",  "price": 329.00,  "weight_kg": 0.24},
    {"sku": "ELEC-005", "name": "iPad Pro 12.9\" M2",           "category": "electronics",  "price": 1099.00, "weight_kg": 0.68},
    {"sku": "APRL-001", "name": "Patagonia Down Jacket",        "category": "apparel",      "price": 279.00,  "weight_kg": 0.85},
    {"sku": "APRL-002", "name": "Levi's 501 Jeans",             "category": "apparel",      "price": 89.50,   "weight_kg": 0.65},
    {"sku": "APRL-003", "name": "Nike Air Max 270",             "category": "apparel",      "price": 159.99,  "weight_kg": 0.72},
    {"sku": "APRL-004", "name": "Cashmere Sweater",             "category": "apparel",      "price": 195.00,  "weight_kg": 0.40},
    {"sku": "FURN-001", "name": "Herman Miller Aeron Chair",    "category": "furniture",    "price": 1495.00, "weight_kg": 19.5},
    {"sku": "FURN-002", "name": "IKEA KALLAX 4x4 Shelf",       "category": "furniture",    "price": 179.00,  "weight_kg": 48.0},
    {"sku": "FURN-003", "name": "Standing Desk 60\"",           "category": "furniture",    "price": 649.00,  "weight_kg": 32.0},
    {"sku": "BOOK-001", "name": "Clean Architecture",           "category": "books",        "price": 44.99,   "weight_kg": 0.55},
    {"sku": "BOOK-002", "name": "Designing Data-Intensive Apps","category": "books",        "price": 59.99,   "weight_kg": 0.92},
    {"sku": "BOOK-003", "name": "The Pragmatic Programmer",     "category": "books",        "price": 49.99,   "weight_kg": 0.48},
]

WAREHOUSES = ["WH-US-EAST-01", "WH-US-WEST-02", "WH-EU-CENTRAL-03", "WH-APAC-04"]

# ── Customer profiles ──────────────────────────────────────────────────────────
CUSTOMERS = [
    {"id": "CUST-ENT-001", "name": "Acme Corp",       "tier": "enterprise", "email": "buyer@acme.com",       "fraud_history": 0,   "credit_score": 820},
    {"id": "CUST-ENT-002", "name": "GlobalTech Ltd",   "tier": "enterprise", "email": "ops@globaltech.io",    "fraud_history": 0,   "credit_score": 795},
    {"id": "CUST-ENT-003", "name": "MegaRetail Inc",   "tier": "enterprise", "email": "purchase@megaret.com", "fraud_history": 0,   "credit_score": 810},
    {"id": "CUST-PRO-001", "name": "Alice Thompson",   "tier": "pro",        "email": "alice@startup.dev",    "fraud_history": 0,   "credit_score": 740},
    {"id": "CUST-PRO-002", "name": "Bob Martinez",     "tier": "pro",        "email": "bob.m@gmail.com",      "fraud_history": 0,   "credit_score": 710},
    {"id": "CUST-PRO-003", "name": "Clara Nguyen",     "tier": "pro",        "email": "clara@techco.net",     "fraud_history": 1,   "credit_score": 695},
    {"id": "CUST-PRO-004", "name": "David Kim",        "tier": "pro",        "email": "d.kim@consulting.co",  "fraud_history": 0,   "credit_score": 760},
    {"id": "CUST-PRO-005", "name": "Eva Johansson",    "tier": "pro",        "email": "eva.j@eu.dev",         "fraud_history": 0,   "credit_score": 730},
    {"id": "CUST-FREE-001","name": "Frank Wilson",     "tier": "free",       "email": "frank.w@yahoo.com",    "fraud_history": 2,   "credit_score": 580},
    {"id": "CUST-FREE-002","name": "Grace Lee",        "tier": "free",       "email": "grace.l@hotmail.com",  "fraud_history": 0,   "credit_score": 640},
    {"id": "CUST-FREE-003","name": "Hector Romero",    "tier": "free",       "email": "h.romero@mail.com",    "fraud_history": 3,   "credit_score": 510},
    {"id": "CUST-FREE-004","name": "Iris Chen",        "tier": "free",       "email": "iris.c@outlook.com",   "fraud_history": 0,   "credit_score": 675},
    {"id": "CUST-FREE-005","name": "Jack O'Brien",     "tier": "free",       "email": "jack.ob@gmail.com",    "fraud_history": 1,   "credit_score": 600},
    {"id": "CUST-FREE-006","name": "Karen Patel",      "tier": "free",       "email": "k.patel@proton.me",    "fraud_history": 0,   "credit_score": 660},
    {"id": "CUST-FREE-007","name": "Liam Foster",      "tier": "free",       "email": "liam.f@icloud.com",    "fraud_history": 0,   "credit_score": 620},
    {"id": "CUST-SUSP-001","name": "Max Suspicious",   "tier": "free",       "email": "max.sus@tempmail.xyz", "fraud_history": 5,   "credit_score": 420},
    {"id": "CUST-SUSP-002","name": "Nova Fraudster",   "tier": "free",       "email": "nova@fakeemail.ru",    "fraud_history": 8,   "credit_score": 380},
    {"id": "CUST-PRO-006", "name": "Olivia Bennett",   "tier": "pro",        "email": "o.bennett@design.co",  "fraud_history": 0,   "credit_score": 755},
    {"id": "CUST-PRO-007", "name": "Paul Schmidt",     "tier": "pro",        "email": "paul.s@berlintech.de", "fraud_history": 0,   "credit_score": 740},
    {"id": "CUST-ENT-004", "name": "QuantumSoft LLC",  "tier": "enterprise", "email": "cto@quantumsoft.ai",   "fraud_history": 0,   "credit_score": 850},
]

PAYMENT_METHODS = ["visa", "mastercard", "amex", "paypal", "apple_pay", "google_pay"]


# ── Helper: traceparent extraction ────────────────────────────────────────────
def inject_traceparent(span) -> str:
    sc = span.get_span_context()
    return f"00-{sc.trace_id:032x}-{sc.span_id:016x}-01"

def extract_context(traceparent: str):
    return propagator.extract({"traceparent": traceparent})


# ── Service functions ─────────────────────────────────────────────────────────

def svc_product_catalog(order_id: str, items: list, parent_tp: str) -> tuple:
    """Fetch product details from catalog service."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with checkout.tracer.start_as_current_span(
        "http.client.product_catalog", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "product-catalog",
                    "http.url": "http://product-catalog/api/v1/products/batch",
                    "order.id": order_id, "rpc.skus": ",".join(i["sku"] for i in items)}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with catalog.tracer.start_as_current_span(
            "catalog.batch_lookup", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v1/products/batch",
                        "order.id": order_id, "catalog.version": "v3.2.1",
                        "catalog.backend": "postgresql-read-replica"}
        ) as entry_span:
            time.sleep(random.uniform(0.02, 0.07))
            enriched = []
            for item in items:
                p = next((p for p in PRODUCTS if p["sku"] == item["sku"]), None)
                if p:
                    enriched.append({**p, "qty": item["qty"]})
                    entry_span.set_attribute(f"product.{item['sku']}.found", True)

            dur_ms = (time.time() - t0) * 1000
            entry_span.set_attribute("catalog.products_returned", len(enriched))
            entry_span.set_attribute("catalog.lookup_ms", round(dur_ms, 2))

            cat_lookups.add(len(items), attributes={"catalog.version": "v3.2.1"})
            cat_latency.record(dur_ms, attributes={"result": "hit"})

            catalog.logger.info(
                f"batch product lookup completed: {len(enriched)} products",
                extra={"order.id": order_id, "catalog.products_returned": len(enriched),
                       "catalog.lookup_ms": round(dur_ms, 2)}
            )
            return enriched, inject_traceparent(entry_span)


def svc_inventory(order_id: str, items: list, parent_tp: str, force_stockout: bool = False) -> tuple:
    """Check inventory availability across warehouses."""
    parent_ctx = extract_context(parent_tp)
    warehouse = random.choice(WAREHOUSES)
    t0 = time.time()

    with checkout.tracer.start_as_current_span(
        "http.client.inventory", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "inventory-service",
                    "http.url": "http://inventory-service/api/v2/reserve",
                    "order.id": order_id}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with inventory.tracer.start_as_current_span(
            "inventory.reserve_items", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v2/reserve",
                        "order.id": order_id, "inventory.warehouse_id": warehouse,
                        "inventory.items_requested": len(items)}
        ) as entry_span:
            time.sleep(random.uniform(0.03, 0.09))
            inv_checks.add(1, attributes={"warehouse": warehouse})

            if force_stockout:
                sku = items[0]["sku"]
                err = Exception(f"InsufficientStockError: SKU {sku} has 0 units available in {warehouse}")
                entry_span.record_exception(err)
                entry_span.set_status(StatusCode.ERROR, str(err))
                entry_span.set_attribute("inventory.out_of_stock_sku", sku)
                entry_span.set_attribute("inventory.warehouse_id", warehouse)
                inv_stockouts.add(1, attributes={"warehouse": warehouse, "sku": sku})
                inventory.logger.error(
                    f"stock reservation failed: {sku} unavailable",
                    extra={"order.id": order_id, "inventory.sku": sku,
                           "inventory.warehouse_id": warehouse, "inventory.available_qty": 0}
                )
                raise err

            reservation_id = f"RES-{uuid.uuid4().hex[:10].upper()}"
            entry_span.set_attribute("inventory.reservation_id", reservation_id)
            entry_span.set_attribute("inventory.warehouse_id", warehouse)
            entry_span.set_attribute("inventory.items_reserved", len(items))

            inventory.logger.info(
                f"inventory reserved: {reservation_id}",
                extra={"order.id": order_id, "inventory.reservation_id": reservation_id,
                       "inventory.warehouse_id": warehouse, "inventory.items_reserved": len(items)}
            )
            return reservation_id, warehouse, inject_traceparent(entry_span)


def svc_pricing_engine(order_id: str, customer: dict, items: list, parent_tp: str,
                        force_timeout: bool = False) -> tuple:
    """Calculate final pricing with discounts and promotions."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()
    base_total = sum(i["price"] * i["qty"] for i in items)

    with checkout.tracer.start_as_current_span(
        "http.client.pricing_engine", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "pricing-engine",
                    "http.url": "http://pricing-engine/api/v1/calculate",
                    "order.id": order_id, "pricing.base_total_usd": base_total}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with pricing.tracer.start_as_current_span(
            "pricing.calculate_order", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v1/calculate",
                        "order.id": order_id, "pricing.engine_version": "v2.4.0",
                        "pricing.model": "dynamic-tiered",
                        "customer.tier": customer["tier"],
                        "pricing.items_count": len(items)}
        ) as entry_span:
            if force_timeout:
                time.sleep(random.uniform(5.0, 8.0))  # simulate slow downstream
                err = Exception("PricingTimeoutError: pricing service exceeded 5s SLA")
                entry_span.record_exception(err)
                entry_span.set_status(StatusCode.ERROR, str(err))
                price_timeouts.add(1, attributes={"customer.tier": customer["tier"]})
                pricing.logger.error(
                    "pricing engine timeout: SLA breach",
                    extra={"order.id": order_id, "pricing.timeout_ms": 5000,
                           "customer.tier": customer["tier"], "pricing.base_total_usd": base_total}
                )
                raise err

            time.sleep(random.uniform(0.04, 0.12))

            # Apply tier discounts
            discount_pct = {"enterprise": 0.15, "pro": 0.08, "free": 0.0}.get(customer["tier"], 0.0)
            discount_usd = round(base_total * discount_pct, 2)
            tax_rate     = 0.085
            subtotal     = round(base_total - discount_usd, 2)
            tax_usd      = round(subtotal * tax_rate, 2)
            shipping_usd = 0.0 if subtotal > 99 else 9.99
            total_usd    = round(subtotal + tax_usd + shipping_usd, 2)

            entry_span.set_attribute("pricing.base_total_usd",    base_total)
            entry_span.set_attribute("pricing.discount_pct",      discount_pct)
            entry_span.set_attribute("pricing.discount_usd",      discount_usd)
            entry_span.set_attribute("pricing.tax_rate",          tax_rate)
            entry_span.set_attribute("pricing.tax_usd",           tax_usd)
            entry_span.set_attribute("pricing.shipping_usd",      shipping_usd)
            entry_span.set_attribute("pricing.total_usd",         total_usd)

            dur_ms = (time.time() - t0) * 1000
            price_calcs.add(1, attributes={"customer.tier": customer["tier"]})

            pricing.logger.info(
                f"pricing calculated: ${total_usd} (discount {discount_pct*100:.0f}%)",
                extra={"order.id": order_id, "pricing.total_usd": total_usd,
                       "pricing.discount_pct": discount_pct, "pricing.tax_usd": tax_usd,
                       "pricing.shipping_usd": shipping_usd, "customer.tier": customer["tier"]}
            )
            return total_usd, discount_usd, inject_traceparent(entry_span)


def svc_fraud_detection(payment_id: str, customer: dict, amount_usd: float,
                         parent_tp: str, force_fraud: bool = False) -> tuple:
    """Run fraud scoring model against the transaction."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with payment.tracer.start_as_current_span(
        "http.client.fraud_detection", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "fraud-detection",
                    "http.url": "http://fraud-detection/api/v3/score",
                    "payment.id": payment_id, "payment.amount_usd": amount_usd}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with fraud.tracer.start_as_current_span(
            "fraud.score_transaction", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v3/score",
                        "payment.id": payment_id, "fraud.model_version": "xgb-v4.1",
                        "fraud.feature_count": 147,
                        "customer.id": customer["id"],
                        "customer.tier": customer["tier"]}
        ) as entry_span:
            time.sleep(random.uniform(0.05, 0.15))
            entry_span.add_event("fraud.features.loaded", {"fraud.feature_count": 147, "fraud.model": "xgb-v4.1"})

            # Compute fraud score based on customer history + amount
            base_score = min(0.05 + (customer["fraud_history"] * 0.12), 0.95)
            if amount_usd > 1000: base_score += 0.08
            if customer["credit_score"] < 600: base_score += 0.10
            if force_fraud: base_score = random.uniform(0.86, 0.99)
            score = round(min(base_score + random.uniform(-0.03, 0.03), 1.0), 4)
            decision = "block" if score > 0.85 else "allow"
            risk_tier = "HIGH" if score > 0.7 else ("MEDIUM" if score > 0.4 else "LOW")

            entry_span.add_event("fraud.model.scored", {"fraud.score": score, "fraud.risk_tier": risk_tier})

            entry_span.set_attribute("fraud.score",         score)
            entry_span.set_attribute("fraud.decision",      decision)
            entry_span.set_attribute("fraud.risk_tier",     risk_tier)
            entry_span.set_attribute("fraud.model_version", "xgb-v4.1")

            dur_ms = (time.time() - t0) * 1000
            fraud_checks.add(1, attributes={"fraud.decision": decision})
            fraud_scores.record(score, attributes={"customer.tier": customer["tier"]})

            if decision == "block":
                entry_span.add_event("fraud.transaction.blocked", {"fraud.score": score, "fraud.block_reason": "score_exceeded_threshold"})
                fraud_blocks.add(1, attributes={"fraud.risk_tier": risk_tier})
                entry_span.record_exception(ValueError(f"Transaction blocked: fraud score {score}"), attributes={"exception.escaped": True})
                entry_span.set_status(StatusCode.ERROR, f"Transaction blocked: fraud score {score}")
                fraud.logger.warning(
                    f"fraud block: score={score} risk={risk_tier} customer={customer['id']}",
                    extra={"payment.id": payment_id, "fraud.score": score,
                           "fraud.risk_tier": risk_tier, "fraud.decision": decision,
                           "customer.id": customer["id"], "fraud.model_version": "xgb-v4.1"}
                )
            else:
                fraud.logger.info(
                    f"fraud check passed: score={score} risk={risk_tier}",
                    extra={"payment.id": payment_id, "fraud.score": score,
                           "fraud.risk_tier": risk_tier, "fraud.decision": decision,
                           "customer.id": customer["id"]}
                )
            return score, decision, inject_traceparent(entry_span)


def svc_payment_processor(payment_id: str, amount_usd: float, method: str,
                            parent_tp: str, force_decline: bool = False) -> tuple:
    """Call Stripe/payment processor to charge the card."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with payment.tracer.start_as_current_span(
        "http.client.stripe_charge", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "api.stripe.com",
                    "http.url": "https://api.stripe.com/v1/charges",
                    "payment.id": payment_id, "payment.amount_usd": amount_usd,
                    "payment.method": method, "payment.provider": "stripe"}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with processor.tracer.start_as_current_span(
            "stripe.charge.create", kind=SpanKind.CLIENT,
            context=extract_context(tp),
            attributes={"http.method": "POST", "net.peer.name": "api.stripe.com",
                        "payment.id": payment_id, "payment.amount_usd": amount_usd,
                        "payment.method": method, "payment.provider": "stripe",
                        "payment.currency": "usd"}
        ) as stripe_span:
            stripe_span.add_event("payment.auth.initiated", {"payment.gateway": "stripe", "payment.amount_usd": amount_usd})
            time.sleep(random.uniform(0.08, 0.25))

            if force_decline:
                charge_id = None
                error_code = random.choice(["card_declined", "insufficient_funds",
                                            "expired_card", "do_not_honor"])
                err = Exception(f"StripeCardError: {error_code}")
                stripe_span.record_exception(err)
                stripe_span.set_status(StatusCode.ERROR, str(err))
                stripe_span.set_attribute("payment.status",     "failed")
                stripe_span.set_attribute("payment.error_code", error_code)
                exit_span.record_exception(err, attributes={"exception.escaped": True})
                exit_span.set_status(StatusCode.ERROR, str(err))

                dur_ms = (time.time() - t0) * 1000
                processor.logger.error(
                    f"stripe charge declined: {error_code}",
                    extra={"payment.id": payment_id, "payment.amount_usd": amount_usd,
                           "payment.error_code": error_code, "payment.method": method}
                )
                return False, None, error_code, inject_traceparent(stripe_span)

            stripe_span.add_event("payment.auth.completed", {"payment.auth_code": f"AUTH-{uuid.uuid4().hex[:8].upper()}"})
            charge_id = f"ch_{uuid.uuid4().hex[:24]}"
            stripe_span.set_attribute("payment.charge_id",  charge_id)
            stripe_span.set_attribute("payment.status",     "succeeded")
            stripe_span.set_attribute("payment.captured",   True)
            stripe_span.set_attribute("payment.network",    random.choice(["visa_net", "mc_net", "amex_net"]))

            dur_ms = (time.time() - t0) * 1000
            processor.logger.info(
                f"stripe charge succeeded: {charge_id} ${amount_usd}",
                extra={"payment.id": payment_id, "payment.charge_id": charge_id,
                       "payment.amount_usd": amount_usd, "payment.method": method}
            )
            return True, charge_id, None, inject_traceparent(stripe_span)


def svc_payment(order_id: str, customer: dict, amount_usd: float, method: str,
                 parent_tp: str, force_fraud: bool = False,
                 force_decline: bool = False) -> tuple:
    """Payment service orchestrates fraud check + charge."""
    parent_ctx = extract_context(parent_tp)
    payment_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"
    t0 = time.time()

    with checkout.tracer.start_as_current_span(
        "http.client.payment_service", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "payment-service",
                    "http.url": "http://payment-service/api/v2/charge",
                    "order.id": order_id, "payment.id": payment_id,
                    "payment.amount_usd": amount_usd}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with payment.tracer.start_as_current_span(
            "payment.process_charge", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v2/charge",
                        "order.id": order_id, "payment.id": payment_id,
                        "payment.amount_usd": amount_usd, "payment.method": method,
                        "customer.id": customer["id"], "customer.tier": customer["tier"]}
        ) as entry_span:
            pay_attempts.add(1, attributes={"payment.method": method})
            pay_value.record(amount_usd, attributes={"payment.method": method,
                                                      "customer.tier": customer["tier"]})
            payment.logger.info(
                f"payment processing started: {payment_id} ${amount_usd}",
                extra={"order.id": order_id, "payment.id": payment_id,
                       "payment.amount_usd": amount_usd, "payment.method": method,
                       "customer.id": customer["id"]}
            )

            # Step 1: fraud detection
            fraud_score, fraud_decision, tp_fraud = svc_fraud_detection(
                payment_id, customer, amount_usd,
                inject_traceparent(entry_span), force_fraud=force_fraud
            )
            if fraud_decision == "block":
                entry_span.record_exception(RuntimeError(f"Payment blocked by fraud detection: score={fraud_score}"), attributes={"exception.escaped": True})
                entry_span.set_status(StatusCode.ERROR, f"Payment blocked by fraud detection: score={fraud_score}")
                entry_span.set_attribute("payment.status",      "fraud_blocked")
                entry_span.set_attribute("fraud.score",         fraud_score)
                exit_span.record_exception(RuntimeError("fraud_blocked"), attributes={"exception.escaped": True})
                exit_span.set_status(StatusCode.ERROR, "fraud_blocked")
                dur_ms = (time.time() - t0) * 1000
                pay_latency.record(dur_ms, attributes={"payment.status": "fraud_blocked"})
                payment.logger.warning(
                    f"payment blocked by fraud: {payment_id} score={fraud_score}",
                    extra={"order.id": order_id, "payment.id": payment_id,
                           "fraud.score": fraud_score, "payment.status": "fraud_blocked"}
                )
                return False, payment_id, "fraud_blocked", None

            # Step 2: charge via processor
            charge_ok, charge_id, error_code, tp_proc = svc_payment_processor(
                payment_id, amount_usd, method,
                inject_traceparent(entry_span), force_decline=force_decline
            )
            if not charge_ok:
                entry_span.record_exception(ValueError(f"Card declined: {error_code}"), attributes={"exception.escaped": True})
                entry_span.set_status(StatusCode.ERROR, f"Card declined: {error_code}")
                entry_span.set_attribute("payment.status",      "declined")
                entry_span.set_attribute("payment.error_code",  error_code)
                exit_span.record_exception(ValueError("card_declined"), attributes={"exception.escaped": True})
                exit_span.set_status(StatusCode.ERROR, "card_declined")
                dur_ms = (time.time() - t0) * 1000
                pay_latency.record(dur_ms, attributes={"payment.status": "declined"})
                payment.logger.error(
                    f"payment declined: {payment_id} error={error_code}",
                    extra={"order.id": order_id, "payment.id": payment_id,
                           "payment.error_code": error_code, "payment.method": method}
                )
                return False, payment_id, error_code, None

            entry_span.set_attribute("payment.status",    "succeeded")
            entry_span.set_attribute("payment.charge_id", charge_id)
            entry_span.set_attribute("fraud.score",       fraud_score)

            dur_ms = (time.time() - t0) * 1000
            pay_latency.record(dur_ms, attributes={"payment.status": "succeeded"})
            payment.logger.info(
                f"payment succeeded: {payment_id} charge={charge_id}",
                extra={"order.id": order_id, "payment.id": payment_id,
                       "payment.charge_id": charge_id, "payment.amount_usd": amount_usd,
                       "fraud.score": fraud_score}
            )
            return True, payment_id, None, charge_id


def svc_notification(order_id: str, customer: dict, total_usd: float,
                      parent_tp: str, order_traceparent: str = None) -> bool:
    """Send order confirmation via email and push notification."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with orders.tracer.start_as_current_span(
        "http.client.notification", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "notification-service",
                    "http.url": "http://notification-service/api/v1/send",
                    "order.id": order_id}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        # Build span links to the order span if an order traceparent was provided
        notify_links = []
        if order_traceparent:
            order_ctx = extract_context(order_traceparent)
            from opentelemetry import trace as _trace
            order_span_ctx = _trace.get_current_span(order_ctx).get_span_context()
            if order_span_ctx and order_span_ctx.is_valid:
                notify_links.append(Link(context=order_span_ctx))

        with notify.tracer.start_as_current_span(
            "notification.send_order_confirmation", kind=SpanKind.SERVER,
            context=extract_context(tp),
            links=notify_links,
            attributes={"http.method": "POST", "http.route": "/api/v1/send",
                        "order.id": order_id, "notification.channel": "email+push",
                        "notification.template": "order_confirmation_v2",
                        "customer.id": customer["id"], "customer.email": customer["email"],
                        "notification.amount_usd": total_usd}
        ) as entry_span:
            time.sleep(random.uniform(0.02, 0.06))

            notif_id = f"NOTIF-{uuid.uuid4().hex[:8].upper()}"
            entry_span.set_attribute("notification.id",          notif_id)
            entry_span.set_attribute("notification.email_sent",  True)
            entry_span.set_attribute("notification.push_sent",   True)

            dur_ms = (time.time() - t0) * 1000
            notif_sent.add(1, attributes={"notification.channel": "email"})
            notif_sent.add(1, attributes={"notification.channel": "push"})
            notif_latency.record(dur_ms, attributes={"notification.template": "order_confirmation_v2"})

            notify.logger.info(
                f"order confirmation sent: {notif_id} to {customer['email']}",
                extra={"order.id": order_id, "notification.id": notif_id,
                       "customer.email": customer["email"], "notification.amount_usd": total_usd}
            )
            return True


def svc_order_service(order_id: str, customer: dict, items: list, warehouse: str,
                       payment_id: str, charge_id: str, total_usd: float,
                       parent_tp: str, force_db_error: bool = False) -> tuple:
    """Create order record and trigger notification."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with checkout.tracer.start_as_current_span(
        "http.client.order_service", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "order-service",
                    "http.url": "http://order-service/api/v1/orders",
                    "order.id": order_id, "payment.id": payment_id}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with orders.tracer.start_as_current_span(
            "order.create", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v1/orders",
                        "order.id": order_id, "order.items_count": len(items),
                        "order.total_usd": total_usd, "order.warehouse_id": warehouse,
                        "customer.id": customer["id"], "customer.tier": customer["tier"],
                        "payment.id": payment_id, "order.db_backend": "postgres-primary"}
        ) as entry_span:
            if force_db_error:
                time.sleep(random.uniform(0.5, 1.2))
                err = Exception("ConnectionRefusedError: postgres-primary:5432 connection refused — all replicas exhausted")
                entry_span.record_exception(err)
                entry_span.set_status(StatusCode.ERROR, str(err))
                exit_span.record_exception(ConnectionRefusedError("postgres-primary:5432 connection refused — all replicas exhausted"), attributes={"exception.escaped": True})
                exit_span.set_status(StatusCode.ERROR, "db_connection_refused")
                order_errors.add(1, attributes={"error.type": "db_connection_refused"})
                orders.logger.error(
                    f"CRITICAL: database connection refused for order {order_id}",
                    extra={"order.id": order_id, "payment.id": payment_id,
                           "order.total_usd": total_usd,
                           "error.type": "db_connection_refused",
                           "order.db_backend": "postgres-primary"}
                )
                raise err

            time.sleep(random.uniform(0.05, 0.12))

            # Write order to DB (simulated)
            with orders.tracer.start_as_current_span(
                "order.db.insert", kind=SpanKind.CLIENT,
                attributes={"db.system": "postgresql", "db.name": "orders",
                            "db.statement": "INSERT INTO orders ...",
                            "db.operation": "INSERT", "order.id": order_id}
            ) as db_span:
                time.sleep(random.uniform(0.01, 0.04))
                db_span.set_attribute("db.rows_affected", 1)
                orders.logger.info("order record persisted to database",
                                   extra={"order.id": order_id, "db.rows_affected": 1})

            entry_span.set_attribute("order.status",     "confirmed")
            entry_span.set_attribute("order.created_at", int(time.time()))

            order_created.add(1, attributes={"customer.tier": customer["tier"],
                                              "order.warehouse_id": warehouse})

            # Trigger notification — pass order span traceparent as a link
            order_tp = inject_traceparent(entry_span)
            notif_ok = svc_notification(order_id, customer, total_usd,
                                         order_tp, order_traceparent=order_tp)

            dur_ms = (time.time() - t0) * 1000
            orders.logger.info(
                f"order created successfully: {order_id} ${total_usd}",
                extra={"order.id": order_id, "payment.id": payment_id,
                       "charge.id": charge_id, "order.total_usd": total_usd,
                       "order.status": "confirmed", "customer.id": customer["id"]}
            )
            return True, inject_traceparent(entry_span)


# ── Main scenario runner ──────────────────────────────────────────────────────

def run_checkout_scenario(scenario_type: str, customer: dict, items: list):
    """Execute a full checkout flow for the given scenario type."""
    order_id = f"ORD-{uuid.uuid4().hex[:10].upper()}"
    method   = random.choice(PAYMENT_METHODS)
    t_start  = time.time()

    force_fraud     = scenario_type == "fraud_block"
    force_decline   = scenario_type == "card_declined"
    force_stockout  = scenario_type == "out_of_stock"
    force_pricing_to= scenario_type == "pricing_timeout"
    force_db_err    = scenario_type == "db_error"

    print(f"\n  [{scenario_type}] order={order_id} customer={customer['id']} "
          f"tier={customer['tier']} method={method}")

    # Set W3C baggage for customer.tier and request.priority
    baggage_ctx = baggage.set_baggage("customer.tier", customer["tier"])
    baggage_ctx = baggage.set_baggage(
        "request.priority",
        "HIGH" if customer["tier"] == "enterprise" else "NORMAL",
        context=baggage_ctx
    )

    # Track active checkouts
    global _active_checkouts
    with _active_checkouts_lock:
        _active_checkouts += 1

    try:
        with checkout.tracer.start_as_current_span(
            "checkout.request", kind=SpanKind.SERVER,
            attributes={"http.method": "POST", "http.route": "/api/v1/checkout",
                        "order.id": order_id, "customer.id": customer["id"],
                        "customer.tier": customer["tier"],
                        "payment.method": method,
                        "checkout.items_count": len(items),
                        "scenario": scenario_type}
        ) as root_span:
            tp_root = inject_traceparent(root_span)

            try:
                # 1. Product catalog lookup
                enriched_items, tp = svc_product_catalog(order_id, items, tp_root)

                # 2. Inventory check
                reservation_id, warehouse, tp = svc_inventory(
                    order_id, enriched_items, tp_root, force_stockout=force_stockout)

                # 3. Pricing engine
                total_usd, discount_usd, tp = svc_pricing_engine(
                    order_id, customer, enriched_items, tp_root,
                    force_timeout=force_pricing_to)

                root_span.set_attribute("order.total_usd",    total_usd)
                root_span.set_attribute("order.discount_usd", discount_usd)

                # 4. Payment (includes fraud + processor)
                pay_ok, payment_id, pay_error, charge_id = svc_payment(
                    order_id, customer, total_usd, method, tp_root,
                    force_fraud=force_fraud, force_decline=force_decline)

                if not pay_ok:
                    root_span.record_exception(RuntimeError(f"Payment failed: {pay_error}"), attributes={"exception.escaped": True})
                    root_span.set_status(StatusCode.ERROR, f"Payment failed: {pay_error}")
                    co_errors.add(1, attributes={"error.type": pay_error})
                    co_requests.add(1, attributes={"result": "payment_failed",
                                                    "customer.tier": customer["tier"]})
                    co_latency.record((time.time() - t_start) * 1000,
                                      attributes={"result": "payment_failed"})
                    tag = "🚫" if "fraud" in pay_error else "❌"
                    print(f"    {tag} Payment failed: {pay_error}")
                    checkout.logger.warning(
                        f"checkout failed: {pay_error}",
                        extra={"order.id": order_id, "payment.error": pay_error,
                               "customer.id": customer["id"]}
                    )
                    return False

                # 5. Create order + notify
                order_ok, tp = svc_order_service(
                    order_id, customer, enriched_items, warehouse,
                    payment_id, charge_id, total_usd, tp_root,
                    force_db_error=force_db_err)

                root_span.set_attribute("order.status", "confirmed")
                root_span.set_attribute("order.id",     order_id)
                dur_ms = (time.time() - t_start) * 1000
                co_requests.add(1, attributes={"result": "success",
                                                "customer.tier": customer["tier"]})
                co_latency.record(dur_ms, attributes={"result": "success"})
                co_value.record(total_usd, attributes={"customer.tier": customer["tier"]})
                checkout.logger.info(
                    f"checkout completed: {order_id} ${total_usd}",
                    extra={"order.id": order_id, "order.total_usd": total_usd,
                           "payment.id": payment_id, "charge.id": charge_id,
                           "customer.id": customer["id"], "checkout.duration_ms": dur_ms}
                )
                print(f"    ✅ Checkout complete: {order_id} ${total_usd:.2f} ({dur_ms:.0f}ms)")
                return True

            except Exception as e:
                root_span.record_exception(e)
                root_span.set_status(StatusCode.ERROR, str(e))
                dur_ms = (time.time() - t_start) * 1000
                err_type = type(e).__name__
                co_errors.add(1, attributes={"error.type": err_type})
                co_requests.add(1, attributes={"result": "error", "customer.tier": customer["tier"]})
                co_latency.record(dur_ms, attributes={"result": "error"})
                checkout.logger.error(
                    f"checkout exception: {e}",
                    extra={"order.id": order_id, "error.type": err_type,
                           "customer.id": customer["id"]}
                )
                if "stockout" in str(e).lower() or "InsufficientStock" in str(e):
                    print(f"    ⚠️  Out of stock: {e}")
                elif "DB" in str(e) or "connection" in str(e).lower():
                    print(f"    ❌ CRITICAL DB error: {e}")
                elif "Timeout" in str(e):
                    print(f"    ⚠️  Service timeout: {e}")
                else:
                    print(f"    ❌ Error: {e}")
                return False
    finally:
        with _active_checkouts_lock:
            _active_checkouts -= 1


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{'='*62}")
    print(f"EDOT-Autopilot | E-Commerce Checkout Platform")
    print(f"{'='*62}")

    # Scenario distribution: 30 total
    # 18 happy, 4 fraud, 3 declined, 2 stockout, 2 pricing timeout, 1 db error
    scenario_pool = (
        ["happy_path"] * 18 +
        ["fraud_block"] * 4 +
        ["card_declined"] * 3 +
        ["out_of_stock"] * 2 +
        ["pricing_timeout"] * 2 +
        ["db_error"] * 1
    )
    random.shuffle(scenario_pool)

    results = []

    for i, scenario in enumerate(scenario_pool):
        customer = random.choice(CUSTOMERS)
        n_items  = random.randint(1, 4)
        items    = [{"sku": p["sku"], "qty": random.randint(1, 3)}
                    for p in random.sample(PRODUCTS, n_items)]

        print(f"\n{'─'*62}")
        print(f"  Scenario {i+1:02d}/30  [{scenario}]")
        try:
            result = run_checkout_scenario(scenario, customer, items)
            status = "OK" if result else "WARN"
            results.append((f"Scenario {i+1:02d}/30 [{scenario}]", status, None))
        except Exception as e:
            results.append((f"Scenario {i+1:02d}/30 [{scenario}]", "ERROR", str(e)))

        time.sleep(random.uniform(0.1, 0.3))

    print(f"\n{'='*62}")
    print("  Flushing all telemetry providers...")
    for svc in [checkout, catalog, inventory, pricing, payment, fraud, processor, orders, notify]:
        svc.flush()

    for scenario_name, status, error_detail in results:
        if status in ("OK", "WARN"):
            check(scenario_name, True)
        else:
            check(scenario_name, False, error_detail or "")

    # ── Span assertions: verify instrumentation correctness ──────────────────────
    # Collect from all o11y instances in this test
    all_spans = []
    all_spans += checkout.get_finished_spans()
    all_spans += catalog.get_finished_spans()
    all_spans += inventory.get_finished_spans()
    all_spans += pricing.get_finished_spans()
    all_spans += payment.get_finished_spans()
    all_spans += fraud.get_finished_spans()
    all_spans += processor.get_finished_spans()
    all_spans += orders.get_finished_spans()
    all_spans += notify.get_finished_spans()
    print("\nSpan assertions:")
    check("At least one span captured across all services",
          len(all_spans) > 0,
          f"got {len(all_spans)} total spans")
    server_spans = [s for s in all_spans if s.kind.name == "SERVER"]
    check("At least one SERVER span emitted",
          len(server_spans) > 0,
          f"got {len(server_spans)} SERVER spans")
    attrs_with_pricing = [s for s in all_spans if s.attributes and "pricing.base_total_usd" in s.attributes]
    check("At least one span carries pricing.base_total_usd attribute",
          len(attrs_with_pricing) > 0,
          f"got {len(attrs_with_pricing)} spans with pricing.base_total_usd")
    svc_names = {s.resource.attributes.get("service.name") for s in all_spans}
    check("All 9 services emitted spans",
          len(svc_names) >= 9,
          f"services with spans: {svc_names}")

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
