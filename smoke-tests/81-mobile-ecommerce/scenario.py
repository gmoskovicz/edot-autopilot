#!/usr/bin/env python3
"""
Mobile E-Commerce — 9-Service Distributed Tracing Scenario
===========================================================

Architecture:
  mobile-shopapp (React Native client)
    → api-gateway-mobile (Node.js/Express BFF)
        → catalog-service (Python/FastAPI)
        → inventory-service-go (Go/Gin)
        → user-profile-service (Ruby/Rails)
    → payment-mobile-service (Java/Spring)
        → fraud-detection-mobile (Python/FastAPI)
        → payment-processor-mobile (Node.js/Stripe)
    → push-notification-service (Node.js/Express)
    → analytics-ingest (Python/FastAPI — fire-and-forget)

20 trace scenarios:
  12 happy-path flows
   8 error / degraded flows

Run:
    cd smoke-tests
    python3 81-mobile-ecommerce/scenario.py
"""

import os, sys, uuid, time, random, threading, hashlib
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")
if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set")
    sys.exit(0)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from o11y_bootstrap import O11yBootstrap

from opentelemetry.trace import SpanKind, StatusCode, Link
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry import baggage
from opentelemetry.baggage.propagation import W3CBaggagePropagator

ENV = os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test")

CHECKS: list[tuple[str, bool, str]] = []
def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

propagator = TraceContextTextMapPropagator()

# ── Per-service O11y bootstrap ────────────────────────────────────────────────
mobile_client = O11yBootstrap("mobile-shopapp", ENDPOINT, API_KEY, ENV, extra_resource_attrs={
    "os.name": "iOS", "os.version": "17.2.1",
    "os.type": "darwin",
    "os.description": "iOS 17.2.1 (21C66)",
    "os.build_id": "21C66",
    "device.model.name": "iPhone 15 Pro",
    "app.version": "4.2.1", "app.name": "ShopApp",
    "telemetry.sdk.name": "opentelemetry-react-native",
    "telemetry.sdk.language": "javascript",
    "network.connection.type": "wifi",
})
gateway       = O11yBootstrap("api-gateway-mobile",       ENDPOINT, API_KEY, ENV, extra_resource_attrs={"framework": "express",     "node.version": "20.10.0",  "telemetry.sdk.language": "javascript"})
catalog_svc   = O11yBootstrap("catalog-service",          ENDPOINT, API_KEY, ENV, extra_resource_attrs={"framework": "fastapi",     "python.version": "3.11.6", "telemetry.sdk.language": "python"})
inventory_svc = O11yBootstrap("inventory-service-go",     ENDPOINT, API_KEY, ENV, extra_resource_attrs={"framework": "gin",         "go.version": "1.21.5",    "telemetry.sdk.language": "go"})
profile_svc   = O11yBootstrap("user-profile-service",     ENDPOINT, API_KEY, ENV, extra_resource_attrs={"framework": "rails",       "ruby.version": "3.2.2",   "telemetry.sdk.language": "ruby"})
payment_svc   = O11yBootstrap("payment-mobile-service",   ENDPOINT, API_KEY, ENV, extra_resource_attrs={"framework": "spring-boot", "java.version": "21",      "telemetry.sdk.language": "java"})
fraud_svc     = O11yBootstrap("fraud-detection-mobile",   ENDPOINT, API_KEY, ENV, extra_resource_attrs={"framework": "fastapi",     "python.version": "3.11.6", "telemetry.sdk.language": "python"})
processor_svc = O11yBootstrap("payment-processor-mobile", ENDPOINT, API_KEY, ENV, extra_resource_attrs={"framework": "express",     "node.version": "20.10.0",  "telemetry.sdk.language": "javascript"})
push_svc      = O11yBootstrap("push-notification-service",ENDPOINT, API_KEY, ENV, extra_resource_attrs={"framework": "express",     "node.version": "20.10.0",  "telemetry.sdk.language": "javascript"})
analytics_svc = O11yBootstrap("analytics-ingest",         ENDPOINT, API_KEY, ENV, extra_resource_attrs={"framework": "fastapi",     "python.version": "3.11.6", "telemetry.sdk.language": "python"})

# ── Metrics instruments ───────────────────────────────────────────────────────
# mobile-shopapp
mob_screen_views   = mobile_client.meter.create_counter("mobile.screen.view",         description="Screen view events")
mob_session_dur    = mobile_client.meter.create_histogram("mobile.session.duration_ms",description="Session duration", unit="ms")
mob_network_req    = mobile_client.meter.create_histogram("mobile.network.request_ms", description="Network request latency", unit="ms")
mob_crashes        = mobile_client.meter.create_counter("mobile.crashes",              description="App crashes recorded")

# api-gateway-mobile
gw_requests        = gateway.meter.create_counter("gateway.requests",                 description="Gateway request count")
gw_latency         = gateway.meter.create_histogram("gateway.latency_ms",             description="Gateway end-to-end latency", unit="ms")

# catalog-service
cat_product_fetch  = catalog_svc.meter.create_counter("catalog.product_fetch",        description="Product detail fetches")
cat_search_latency = catalog_svc.meter.create_histogram("catalog.search_latency_ms",  description="Search latency", unit="ms")

# inventory-service-go
inv_checks         = inventory_svc.meter.create_counter("inventory.checks",           description="Inventory check count")
inv_stockouts      = inventory_svc.meter.create_counter("inventory.stockouts",         description="Stockout events")

# user-profile-service
prof_lookups       = profile_svc.meter.create_counter("profile.lookups",              description="Profile lookup count")
prof_cache_hits    = profile_svc.meter.create_counter("profile.cache_hits",           description="Profile cache hits")

# payment-mobile-service
pay_attempts       = payment_svc.meter.create_counter("payment.attempts",             description="Payment attempt count")
pay_value          = payment_svc.meter.create_histogram("payment.value_usd",          description="Payment amounts", unit="USD")

# fraud-detection-mobile
fraud_checks       = fraud_svc.meter.create_counter("fraud.checks",                   description="Fraud check count")
fraud_blocks       = fraud_svc.meter.create_counter("fraud.blocks",                   description="Fraud blocks")
fraud_score_hist   = fraud_svc.meter.create_histogram("fraud.score",                  description="Fraud score distribution")

# payment-processor-mobile
proc_charges       = processor_svc.meter.create_counter("processor.charges",          description="Charges processed")
proc_duration      = processor_svc.meter.create_histogram("processor.duration_ms",    description="Charge duration", unit="ms")

# push-notification-service
push_sent          = push_svc.meter.create_counter("push.sent",                       description="Push notifications sent")
push_delivered     = push_svc.meter.create_counter("push.delivered",                  description="Push notifications delivered")

# analytics-ingest
events_ingested    = analytics_svc.meter.create_counter("events.ingested",            description="Analytics events ingested")

# ── Observable gauges ─────────────────────────────────────────────────────────
_active_sessions = 0
_active_sessions_lock = threading.Lock()

def _active_sessions_callback(options):
    from opentelemetry.metrics import Observation
    with _active_sessions_lock:
        yield Observation(_active_sessions, {"env": ENV})

def _gateway_pool_callback(options):
    from opentelemetry.metrics import Observation
    yield Observation(random.randint(8, 32), {"gateway": "api-gateway-mobile"})

def _fraud_model_cache_callback(options):
    from opentelemetry.metrics import Observation
    yield Observation(random.uniform(0.80, 0.97), {"model": "mobile-fraud-v2.3"})

mobile_client.meter.create_observable_gauge(
    "mobile.active_sessions", [_active_sessions_callback],
    description="Currently active mobile sessions"
)
gateway.meter.create_observable_gauge(
    "gateway.connection_pool_size", [_gateway_pool_callback],
    description="Active gateway upstream connections"
)
fraud_svc.meter.create_observable_gauge(
    "fraud.model_cache_hit_ratio", [_fraud_model_cache_callback],
    description="Fraud model feature cache hit ratio"
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

DEVICES = [
    {"id": "DEV-IOS-001",  "model": "iPhone 15 Pro",         "os": "iOS",     "os_version": "17.2.1", "network": "wifi"},
    {"id": "DEV-IOS-002",  "model": "iPhone 14",             "os": "iOS",     "os_version": "16.7.2", "network": "cellular-5g"},
    {"id": "DEV-AND-001",  "model": "Samsung Galaxy S24",    "os": "Android", "os_version": "14",     "network": "wifi"},
    {"id": "DEV-AND-002",  "model": "Google Pixel 8 Pro",    "os": "Android", "os_version": "14",     "network": "cellular-lte"},
    {"id": "DEV-AND-003",  "model": "OnePlus 12",            "os": "Android", "os_version": "14",     "network": "wifi"},
]

CUSTOMERS = [
    {"id": "MCUST-ENT-001", "name": "Apex Retail Corp",   "tier": "enterprise", "email": "buyer@apexretail.com",   "fraud_history": 0, "credit_score": 840, "stored_payment": True},
    {"id": "MCUST-ENT-002", "name": "GlobalShop Ltd",     "tier": "enterprise", "email": "ops@globalshop.io",      "fraud_history": 0, "credit_score": 810, "stored_payment": True},
    {"id": "MCUST-PRO-001", "name": "Alice Fernandez",    "tier": "pro",        "email": "alice.f@startup.dev",    "fraud_history": 0, "credit_score": 745, "stored_payment": True},
    {"id": "MCUST-PRO-002", "name": "Bob Nakamura",       "tier": "pro",        "email": "bob.n@techco.jp",        "fraud_history": 0, "credit_score": 720, "stored_payment": True},
    {"id": "MCUST-PRO-003", "name": "Clara Santos",       "tier": "pro",        "email": "clara.s@design.br",      "fraud_history": 1, "credit_score": 690, "stored_payment": False},
    {"id": "MCUST-FREE-001","name": "Dan Okafor",         "tier": "free",       "email": "dan.o@example.com",       "fraud_history": 0, "credit_score": 650, "stored_payment": False},
    {"id": "MCUST-FREE-002","name": "Eva Müller",         "tier": "free",       "email": "eva.m@example.com",       "fraud_history": 0, "credit_score": 670, "stored_payment": False},
    {"id": "MCUST-FREE-003","name": "Frank Osei",         "tier": "free",       "email": "frank.o@example.com",     "fraud_history": 2, "credit_score": 590, "stored_payment": False},
    {"id": "MCUST-SUSP-001","name": "Grace Anon",         "tier": "free",       "email": "grace@tempmail.invalid",  "fraud_history": 6, "credit_score": 410, "stored_payment": False},
    {"id": "MCUST-GUEST-001","name": "Guest User",        "tier": "guest",      "email": "",                        "fraud_history": 0, "credit_score": 0,   "stored_payment": False},
]

PRODUCTS = [
    {"sku": "MAPP-001", "name": "AirPods Pro 2nd Gen",        "category": "audio",       "price": 249.00, "inventory": 120},
    {"sku": "MAPP-002", "name": "Apple Watch Ultra 2",         "category": "wearables",   "price": 799.00, "inventory": 45},
    {"sku": "MAPP-003", "name": "Samsung Galaxy Buds2 Pro",    "category": "audio",       "price": 179.99, "inventory": 80},
    {"sku": "MAPP-004", "name": "Anker 100W USB-C Charger",    "category": "accessories", "price": 35.99,  "inventory": 500},
    {"sku": "MAPP-005", "name": "Peak Design Phone Case",      "category": "accessories", "price": 59.95,  "inventory": 200},
    {"sku": "MAPP-006", "name": "Nike Dri-FIT Running Tee",    "category": "apparel",     "price": 34.99,  "inventory": 1},   # near-stockout
    {"sku": "MAPP-007", "name": "Lululemon Align Leggings",    "category": "apparel",     "price": 128.00, "inventory": 30},
    {"sku": "MAPP-008", "name": "Ember Mug 2 (14oz)",          "category": "lifestyle",   "price": 149.95, "inventory": 60},
    {"sku": "MAPP-009", "name": "Moleskine Pro Notebook",      "category": "stationery",  "price": 29.99,  "inventory": 300},
    {"sku": "MAPP-010", "name": "Yeti Rambler 30oz Tumbler",   "category": "lifestyle",   "price": 44.99,  "inventory": 150},
]

PAYMENT_METHODS = ["apple_pay", "google_pay", "visa", "mastercard", "amex", "paypal"]
WAREHOUSES      = ["WH-US-EAST-01", "WH-US-WEST-02", "WH-EU-CENTRAL-03", "WH-APAC-04"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def inject_traceparent(span) -> str:
    sc = span.get_span_context()
    return f"00-{sc.trace_id:032x}-{sc.span_id:016x}-01"

def extract_context(traceparent: str):
    return propagator.extract({"traceparent": traceparent})


# ── Service functions ─────────────────────────────────────────────────────────

def svc_mobile_app_launch(session_id: str, device: dict, parent_tp: str = None):
    """Mobile client emits an app-launch span (root or child)."""
    ctx = extract_context(parent_tp) if parent_tp else None
    t0 = time.time()

    kwargs = dict(
        kind=SpanKind.CLIENT,
        attributes={
            "session.id":                 session_id,
            "device.id":                  hashlib.sha256(device["id"].encode()).hexdigest()[:16],
            "device.model.name":          device["model"],
            "os.name":                    device["os"],
            "os.version":                 device["os_version"],
            "network.connection.type":    device["network"],
            "app.version":                "4.2.1",
            "mobile.screen.name":         "AppLaunch",
        },
    )
    if ctx:
        kwargs["context"] = ctx

    with mobile_client.tracer.start_as_current_span("mobile.app.launch", **kwargs) as span:
        time.sleep(random.uniform(0.03, 0.08))
        dur_ms = (time.time() - t0) * 1000
        span.set_attribute("mobile.launch_ms", round(dur_ms, 2))
        mob_screen_views.add(1, attributes={"screen": "AppLaunch", "os": device["os"]})
        mob_session_dur.record(dur_ms, attributes={"os": device["os"]})
        mobile_client.logger.info(
            f"app launched: session={session_id} device={device['model']}",
            extra={"session.id": session_id, "device.model": device["model"],
                   "network.connection.type": device["network"], "mobile.launch_ms": round(dur_ms, 2)}
        )
        return inject_traceparent(span)


def svc_gateway_route(session_id: str, endpoint: str, method: str, parent_tp: str):
    """BFF gateway routes mobile request to upstream services."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with mobile_client.tracer.start_as_current_span(
        "http.client.api_gateway", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={
            "http.request.method": method, "server.address": "api-gateway-mobile",
            "url.full": f"https://api.shopapp.io{endpoint}",
            "session.id": session_id,
            "service.peer.name": "api-gateway-mobile",
        }
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with gateway.tracer.start_as_current_span(
            "gateway.route", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={
                "http.request.method": method, "http.route": endpoint,
                "session.id": session_id, "gateway.version": "v2.1.0",
                "gateway.upstream": "internal-cluster",
            }
        ) as entry_span:
            time.sleep(random.uniform(0.01, 0.04))
            dur_ms = (time.time() - t0) * 1000
            entry_span.set_attribute("gateway.latency_ms", round(dur_ms, 2))
            gw_requests.add(1, attributes={"http.route": endpoint, "http.request.method": method})
            gw_latency.record(dur_ms, attributes={"http.route": endpoint})
            gateway.logger.info(
                f"gateway routed: {method} {endpoint}",
                extra={"session.id": session_id, "http.request.method": method,
                       "http.route": endpoint, "gateway.latency_ms": round(dur_ms, 2)}
            )
            return inject_traceparent(entry_span)


def svc_catalog_fetch(product_ids: list, parent_tp: str, force_timeout: bool = False):
    """Catalog service fetches product details (FastAPI)."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with gateway.tracer.start_as_current_span(
        "http.client.catalog", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={
            "http.request.method": "POST", "server.address": "catalog-service",
            "url.full": "http://catalog-service/v1/products/batch",
            "catalog.product_count": len(product_ids),
            "service.peer.name": "catalog-service",
        }
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with catalog_svc.tracer.start_as_current_span(
            "catalog.batch_fetch", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={
                "http.request.method": "POST", "http.route": "/v1/products/batch",
                "catalog.product_count": len(product_ids),
                "catalog.backend": "elasticsearch",
                "catalog.version": "v4.0.1",
            }
        ) as entry_span:
            if force_timeout:
                time.sleep(random.uniform(4.0, 6.0))
                err = Exception("CatalogTimeoutError: product detail API exceeded 4s SLA — returning cached stale data")
                entry_span.record_exception(err, attributes={"exception.escaped": False})
                entry_span.set_status(StatusCode.ERROR, str(err))
                entry_span.set_attribute("error.type", type(err).__name__)
                exit_span.record_exception(err, attributes={"exception.escaped": False})
                exit_span.set_status(StatusCode.ERROR, str(err))
                exit_span.set_attribute("error.type", type(err).__name__)
                catalog_svc.logger.warning(
                    "catalog timeout: serving stale cached data",
                    extra={"catalog.product_count": len(product_ids), "catalog.stale": True}
                )
                # Return stale cached data — non-fatal degradation
                products = [p for p in PRODUCTS if p["sku"] in product_ids]
                return products, inject_traceparent(entry_span), True  # stale=True

            time.sleep(random.uniform(0.03, 0.09))
            products = [p for p in PRODUCTS if p["sku"] in product_ids]
            dur_ms = (time.time() - t0) * 1000
            entry_span.set_attribute("catalog.products_returned", len(products))
            entry_span.set_attribute("catalog.lookup_ms", round(dur_ms, 2))
            cat_product_fetch.add(len(product_ids), attributes={"catalog.version": "v4.0.1"})
            cat_search_latency.record(dur_ms, attributes={"result": "hit"})
            catalog_svc.logger.info(
                f"catalog fetch: {len(products)} products returned",
                extra={"catalog.product_count": len(product_ids),
                       "catalog.products_returned": len(products),
                       "catalog.lookup_ms": round(dur_ms, 2)}
            )
            return products, inject_traceparent(entry_span), False  # stale=False


def svc_inventory_check(product_ids: list, warehouse: str, parent_tp: str,
                         force_stockout: bool = False):
    """Inventory service checks stock levels (Go/Gin)."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with gateway.tracer.start_as_current_span(
        "http.client.inventory", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={
            "http.request.method": "POST", "server.address": "inventory-service-go",
            "url.full": "http://inventory-service-go/api/v2/check",
            "inventory.product_count": len(product_ids),
            "inventory.warehouse_id": warehouse,
            "service.peer.name": "inventory-service-go",
        }
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with inventory_svc.tracer.start_as_current_span(
            "inventory.check_stock", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={
                "http.request.method": "POST", "http.route": "/api/v2/check",
                "inventory.warehouse_id": warehouse,
                "inventory.product_count": len(product_ids),
                "inventory.backend": "redis-cluster",
            }
        ) as entry_span:
            time.sleep(random.uniform(0.02, 0.06))
            inv_checks.add(1, attributes={"warehouse": warehouse})

            if force_stockout:
                sku = product_ids[0]
                err = Exception(f"InsufficientStockError: SKU {sku} has 0 units in {warehouse}")
                entry_span.record_exception(err, attributes={"exception.escaped": True})
                entry_span.set_status(StatusCode.ERROR, str(err))
                entry_span.set_attribute("error.type", type(err).__name__)
                entry_span.set_attribute("inventory.out_of_stock_sku", sku)
                exit_span.record_exception(err, attributes={"exception.escaped": True})
                exit_span.set_status(StatusCode.ERROR, str(err))
                exit_span.set_attribute("error.type", type(err).__name__)
                inv_stockouts.add(1, attributes={"warehouse": warehouse, "sku": sku})
                inventory_svc.logger.error(
                    f"stockout: {sku} unavailable in {warehouse}",
                    extra={"inventory.sku": sku, "inventory.warehouse_id": warehouse,
                           "inventory.available_qty": 0}
                )
                raise err

            reservation_id = f"RES-{uuid.uuid4().hex[:10].upper()}"
            entry_span.set_attribute("inventory.reservation_id", reservation_id)
            entry_span.set_attribute("inventory.items_reserved", len(product_ids))
            dur_ms = (time.time() - t0) * 1000
            inventory_svc.logger.info(
                f"inventory reserved: {reservation_id} ({len(product_ids)} items, {warehouse})",
                extra={"inventory.reservation_id": reservation_id,
                       "inventory.warehouse_id": warehouse,
                       "inventory.items_reserved": len(product_ids),
                       "inventory.check_ms": round(dur_ms, 2)}
            )
            return reservation_id, inject_traceparent(entry_span)


def svc_profile_load(user_id: str, parent_tp: str, force_503: bool = False):
    """User profile service loads customer data (Ruby/Rails)."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with gateway.tracer.start_as_current_span(
        "http.client.user_profile", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={
            "http.request.method": "GET", "server.address": "user-profile-service",
            "url.full": f"http://user-profile-service/api/v1/users/{user_id}",
            "user.id": user_id,
            "service.peer.name": "user-profile-service",
        }
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with profile_svc.tracer.start_as_current_span(
            "profile.load_user", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={
                "http.request.method": "GET", "http.route": "/api/v1/users/:id",
                "user.id": user_id, "profile.backend": "postgres",
                "profile.cache_layer": "memcached",
            }
        ) as entry_span:
            if force_503:
                err = Exception("ServiceUnavailableError: user-profile-service 503 — all pods in crash loop")
                entry_span.record_exception(err, attributes={"exception.escaped": False})
                entry_span.set_status(StatusCode.ERROR, str(err))
                entry_span.set_attribute("error.type", type(err).__name__)
                exit_span.record_exception(err, attributes={"exception.escaped": False})
                exit_span.set_status(StatusCode.ERROR, str(err))
                exit_span.set_attribute("error.type", type(err).__name__)
                profile_svc.logger.error(
                    f"profile service 503: graceful degradation to guest mode",
                    extra={"user.id": user_id, "profile.degraded": True,
                           "profile.fallback": "guest_mode"}
                )
                return None, inject_traceparent(entry_span)  # None = degraded guest mode

            time.sleep(random.uniform(0.02, 0.07))
            cache_hit = random.random() > 0.4
            entry_span.set_attribute("profile.cache_hit", cache_hit)
            dur_ms = (time.time() - t0) * 1000
            prof_lookups.add(1, attributes={"user.id": user_id})
            if cache_hit:
                prof_cache_hits.add(1, attributes={"user.id": user_id})
            profile_svc.logger.info(
                f"profile loaded: user={user_id} cache_hit={cache_hit}",
                extra={"user.id": user_id, "profile.cache_hit": cache_hit,
                       "profile.load_ms": round(dur_ms, 2)}
            )
            return {"user_id": user_id, "addresses": 2, "saved_cards": 1}, inject_traceparent(entry_span)


def svc_fraud_check(payment_id: str, customer: dict, amount: float,
                    parent_tp: str, force_fraud: bool = False):
    """Fraud detection scores the mobile transaction."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with payment_svc.tracer.start_as_current_span(
        "http.client.fraud_detection", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={
            "http.request.method": "POST", "server.address": "fraud-detection-mobile",
            "url.full": "http://fraud-detection-mobile/v3/score",
            "payment.id": payment_id, "payment.amount_usd": amount,
            "service.peer.name": "fraud-detection-mobile",
        }
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with fraud_svc.tracer.start_as_current_span(
            "fraud.score_transaction", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={
                "http.request.method": "POST", "http.route": "/v3/score",
                "payment.id": payment_id, "fraud.model_version": "mobile-fraud-v2.3",
                "fraud.feature_count": 89,
                "customer.id": customer["id"], "customer.tier": customer["tier"],
            }
        ) as entry_span:
            time.sleep(random.uniform(0.04, 0.12))
            entry_span.add_event("fraud.features.loaded",
                                 {"fraud.feature_count": 89, "fraud.model": "mobile-fraud-v2.3"})

            base_score = min(0.04 + (customer["fraud_history"] * 0.11), 0.95)
            if amount > 500:  base_score += 0.07
            if customer["credit_score"] < 600: base_score += 0.09
            if force_fraud: base_score = random.uniform(0.88, 0.99)
            score    = round(min(base_score + random.uniform(-0.03, 0.03), 1.0), 4)
            decision = "block" if score > 0.85 else "allow"
            risk     = "HIGH" if score > 0.7 else ("MEDIUM" if score > 0.4 else "LOW")

            entry_span.add_event("fraud.model.scored",
                                 {"fraud.score": score, "fraud.risk_tier": risk})
            entry_span.set_attribute("fraud.score",         score)
            entry_span.set_attribute("fraud.decision",      decision)
            entry_span.set_attribute("fraud.risk_tier",     risk)
            entry_span.set_attribute("fraud.model_version", "mobile-fraud-v2.3")

            fraud_checks.add(1, attributes={"fraud.decision": decision})
            fraud_score_hist.record(score, attributes={"customer.tier": customer["tier"]})

            if decision == "block":
                entry_span.add_event("fraud.transaction.blocked",
                                     {"fraud.score": score, "fraud.block_reason": "score_exceeded_threshold"})
                fraud_blocks.add(1, attributes={"fraud.risk_tier": risk})
                entry_span.record_exception(
                    ValueError(f"Transaction blocked: fraud score {score}"),
                    attributes={"exception.escaped": False}
                )
                entry_span.set_status(StatusCode.ERROR, f"Transaction blocked: fraud score {score}")
                entry_span.set_attribute("error.type", "ValueError")
                exit_span.record_exception(
                    ValueError("fraud_blocked"), attributes={"exception.escaped": False}
                )
                exit_span.set_status(StatusCode.ERROR, "fraud_blocked")
                exit_span.set_attribute("error.type", "ValueError")
                fraud_svc.logger.warning(
                    f"fraud block: score={score} risk={risk} customer={customer['id']}",
                    extra={"payment.id": payment_id, "fraud.score": score,
                           "fraud.risk_tier": risk, "fraud.decision": decision,
                           "customer.id": customer["id"]}
                )
            else:
                fraud_svc.logger.info(
                    f"fraud check passed: score={score} risk={risk}",
                    extra={"payment.id": payment_id, "fraud.score": score,
                           "fraud.decision": decision, "customer.id": customer["id"]}
                )

            dur_ms = (time.time() - t0) * 1000
            return score, decision, inject_traceparent(entry_span)


def svc_payment_charge(payment_id: str, customer: dict, amount: float,
                        parent_tp: str, force_decline: bool = False):
    """Payment mobile service: fraud check + charge via Stripe."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with mobile_client.tracer.start_as_current_span(
        "http.client.payment", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={
            "http.request.method": "POST", "server.address": "payment-mobile-service",
            "url.full": "https://pay.shopapp.io/v2/charge",
            "payment.id": payment_id, "payment.amount_usd": amount,
            "customer.id": customer["id"],
            "service.peer.name": "payment-mobile-service",
        }
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with payment_svc.tracer.start_as_current_span(
            "payment.process_charge", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={
                "http.request.method": "POST", "http.route": "/v2/charge",
                "payment.id": payment_id, "payment.amount_usd": amount,
                "customer.id": customer["id"], "customer.tier": customer["tier"],
                "payment.framework": "spring-boot",
            }
        ) as entry_span:
            pay_attempts.add(1, attributes={"customer.tier": customer["tier"]})
            pay_value.record(amount, attributes={"customer.tier": customer["tier"]})
            payment_svc.logger.info(
                f"payment started: {payment_id} ${amount}",
                extra={"payment.id": payment_id, "payment.amount_usd": amount,
                       "customer.id": customer["id"]}
            )

            # Step 1: fraud check
            fraud_score, fraud_decision, tp_fraud = svc_fraud_check(
                payment_id, customer, amount, inject_traceparent(entry_span)
            )
            if fraud_decision == "block":
                entry_span.record_exception(
                    RuntimeError(f"Payment blocked by fraud: score={fraud_score}"),
                    attributes={"exception.escaped": False}
                )
                entry_span.set_status(StatusCode.ERROR, f"fraud_blocked score={fraud_score}")
                entry_span.set_attribute("error.type", "RuntimeError")
                entry_span.set_attribute("payment.status",  "fraud_blocked")
                entry_span.set_attribute("fraud.score",     fraud_score)
                exit_span.record_exception(
                    RuntimeError("fraud_blocked"), attributes={"exception.escaped": False}
                )
                exit_span.set_status(StatusCode.ERROR, "fraud_blocked")
                exit_span.set_attribute("error.type", "RuntimeError")
                return False, "fraud_blocked", fraud_score, None

            # Step 2: charge via processor
            with payment_svc.tracer.start_as_current_span(
                "http.client.stripe", kind=SpanKind.CLIENT,
                attributes={
                    "http.request.method": "POST", "server.address": "payment-processor-mobile",
                    "url.full": "http://payment-processor-mobile/v1/charges",
                    "payment.id": payment_id, "payment.amount_usd": amount,
                    "service.peer.name": "payment-processor-mobile",
                }
            ) as proc_exit:
                proc_tp = inject_traceparent(proc_exit)

                with processor_svc.tracer.start_as_current_span(
                    "stripe.charge.create", kind=SpanKind.CLIENT,
                    context=extract_context(proc_tp),
                    attributes={
                        "http.request.method": "POST", "server.address": "api.stripe.com",
                        "payment.id": payment_id, "payment.amount_usd": amount,
                        "payment.currency": "usd", "payment.provider": "stripe",
                        "service.peer.name": "api.stripe.com",
                    }
                ) as stripe_span:
                    stripe_span.add_event("payment.auth.initiated",
                                         {"payment.gateway": "stripe", "payment.amount_usd": amount})
                    time.sleep(random.uniform(0.08, 0.22))

                    if force_decline:
                        error_code = random.choice(["card_declined", "insufficient_funds",
                                                    "expired_card", "do_not_honor"])
                        err = Exception(f"StripeCardError: {error_code}")
                        stripe_span.record_exception(err, attributes={"exception.escaped": False})
                        stripe_span.set_status(StatusCode.ERROR, str(err))
                        stripe_span.set_attribute("error.type", type(err).__name__)
                        stripe_span.set_attribute("payment.status",     "failed")
                        stripe_span.set_attribute("payment.error_code", error_code)
                        proc_exit.record_exception(err, attributes={"exception.escaped": False})
                        proc_exit.set_status(StatusCode.ERROR, str(err))
                        proc_exit.set_attribute("error.type", type(err).__name__)
                        entry_span.record_exception(
                            ValueError(f"Card declined: {error_code}"),
                            attributes={"exception.escaped": False}
                        )
                        entry_span.set_status(StatusCode.ERROR, f"declined: {error_code}")
                        entry_span.set_attribute("error.type", "ValueError")
                        entry_span.set_attribute("payment.status",     "declined")
                        entry_span.set_attribute("payment.error_code", error_code)
                        exit_span.record_exception(
                            ValueError("card_declined"), attributes={"exception.escaped": False}
                        )
                        exit_span.set_status(StatusCode.ERROR, "card_declined")
                        exit_span.set_attribute("error.type", "ValueError")
                        t_proc = (time.time() - t0) * 1000
                        proc_charges.add(1, attributes={"payment.status": "declined"})
                        proc_duration.record(t_proc, attributes={"payment.status": "declined"})
                        processor_svc.logger.error(
                            f"stripe charge declined: {error_code}",
                            extra={"payment.id": payment_id, "payment.error_code": error_code}
                        )
                        return False, error_code, fraud_score, None

                    charge_id = f"ch_{uuid.uuid4().hex[:24]}"
                    stripe_span.add_event("payment.auth.completed",
                                          {"payment.auth_code": f"AUTH-{uuid.uuid4().hex[:8].upper()}"})
                    stripe_span.set_attribute("payment.charge_id", charge_id)
                    stripe_span.set_attribute("payment.status",    "succeeded")
                    stripe_span.set_attribute("payment.captured",  True)

                    t_proc = (time.time() - t0) * 1000
                    proc_charges.add(1, attributes={"payment.status": "succeeded"})
                    proc_duration.record(t_proc, attributes={"payment.status": "succeeded"})
                    processor_svc.logger.info(
                        f"stripe charge succeeded: {charge_id}",
                        extra={"payment.id": payment_id, "payment.charge_id": charge_id,
                               "payment.amount_usd": amount}
                    )

            entry_span.set_attribute("payment.status",    "succeeded")
            entry_span.set_attribute("payment.charge_id", charge_id)
            entry_span.set_attribute("fraud.score",       fraud_score)
            dur_ms = (time.time() - t0) * 1000
            payment_svc.logger.info(
                f"payment succeeded: {payment_id} charge={charge_id}",
                extra={"payment.id": payment_id, "payment.charge_id": charge_id,
                       "payment.amount_usd": amount, "fraud.score": fraud_score}
            )
            return True, None, fraud_score, charge_id


def svc_push_notify(user_id: str, message_type: str, parent_tp: str,
                    force_token_expired: bool = False):
    """Push notification service sends APNs/FCM message."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with mobile_client.tracer.start_as_current_span(
        "http.client.push_notify", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={
            "http.request.method": "POST", "server.address": "push-notification-service",
            "url.full": "http://push-notification-service/v1/send",
            "user.id": user_id, "push.message_type": message_type,
            "service.peer.name": "push-notification-service",
        }
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with push_svc.tracer.start_as_current_span(
            "push.send_notification", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={
                "http.request.method": "POST", "http.route": "/v1/send",
                "user.id": user_id, "push.message_type": message_type,
                "push.provider": "apns",
            }
        ) as entry_span:
            time.sleep(random.uniform(0.02, 0.06))

            if force_token_expired:
                # Silent failure — APNs device token expired, non-fatal
                err = Exception("APNsError: device token expired (BadDeviceToken) — silent failure")
                entry_span.record_exception(err, attributes={"exception.escaped": False})
                entry_span.set_status(StatusCode.ERROR, str(err))
                entry_span.set_attribute("error.type", type(err).__name__)
                entry_span.set_attribute("push.delivered", False)
                entry_span.set_attribute("push.error",     "BadDeviceToken")
                push_sent.add(1, attributes={"push.provider": "apns", "push.status": "failed"})
                push_svc.logger.warning(
                    f"push failed: APNs BadDeviceToken for user={user_id} (non-fatal)",
                    extra={"user.id": user_id, "push.message_type": message_type,
                           "push.error": "BadDeviceToken", "push.fatal": False}
                )
                # Intentionally NOT propagating error upward — silent failure
                return False, inject_traceparent(entry_span)

            notif_id = f"PUSH-{uuid.uuid4().hex[:10].upper()}"
            entry_span.set_attribute("push.notification_id", notif_id)
            entry_span.set_attribute("push.delivered",       True)
            dur_ms = (time.time() - t0) * 1000
            push_sent.add(1, attributes={"push.provider": "apns", "push.status": "sent"})
            push_delivered.add(1, attributes={"push.message_type": message_type})
            push_svc.logger.info(
                f"push sent: {notif_id} type={message_type} user={user_id}",
                extra={"push.notification_id": notif_id, "user.id": user_id,
                       "push.message_type": message_type, "push.latency_ms": round(dur_ms, 2)}
            )
            return True, inject_traceparent(entry_span)


def svc_analytics_event(event_type: str, properties: dict, parent_tp: str):
    """Analytics ingest — fire-and-forget, no response required."""
    parent_ctx = extract_context(parent_tp)

    with mobile_client.tracer.start_as_current_span(
        "http.client.analytics", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={
            "http.request.method": "POST", "server.address": "analytics-ingest",
            "url.full": "http://analytics-ingest/v1/events",
            "analytics.event_type": event_type,
            "service.peer.name": "analytics-ingest",
        }
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with analytics_svc.tracer.start_as_current_span(
            "analytics.ingest_event", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={
                "http.request.method": "POST", "http.route": "/v1/events",
                "analytics.event_type": event_type,
                "analytics.backend": "kafka",
            }
        ) as entry_span:
            time.sleep(random.uniform(0.005, 0.02))
            entry_span.set_attribute("analytics.properties_count", len(properties))
            events_ingested.add(1, attributes={"analytics.event_type": event_type})
            analytics_svc.logger.info(
                f"event ingested: {event_type}",
                extra={"analytics.event_type": event_type,
                       "analytics.properties_count": len(properties)}
            )


# ── Scenario runner ───────────────────────────────────────────────────────────

global _active_sessions

def run_scenario(label: str, customer: dict, device: dict, scenario_fn):
    """Wrap a scenario with a root mobile span and session tracking."""
    session_id = f"SES-{uuid.uuid4().hex[:12].upper()}"

    global _active_sessions
    with _active_sessions_lock:
        _active_sessions += 1

    try:
        return scenario_fn(session_id, customer, device)
    finally:
        with _active_sessions_lock:
            _active_sessions -= 1


# ── Individual scenario implementations ──────────────────────────────────────

def scen_app_launch_home_feed(session_id, customer, device):
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/home-feed", "GET", tp)
    product_ids = [p["sku"] for p in random.sample(PRODUCTS, 3)]
    products, _, stale = svc_catalog_fetch(product_ids, gw_tp)
    profile, _ = svc_profile_load(customer["id"], gw_tp)
    mob_screen_views.add(1, attributes={"screen": "HomeFeed", "os": device["os"]})
    svc_analytics_event("screen_view", {"screen": "HomeFeed", "session_id": session_id}, tp)
    return True, f"3 catalog lookups, profile {'loaded' if profile else 'guest mode'}"


def scen_search_products(session_id, customer, device):
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/search?q=wireless+headphones", "GET", tp)
    product_ids = [p["sku"] for p in random.sample(PRODUCTS, 4)]
    products, _, _ = svc_catalog_fetch(product_ids, gw_tp)
    mob_screen_views.add(1, attributes={"screen": "SearchResults", "os": device["os"]})
    svc_analytics_event("search", {"query": "wireless headphones", "results": len(products)}, tp)
    return True, f"{len(products)} results, tapped product detail"


def scen_add_to_cart_checkout(session_id, customer, device):
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/cart/add", "POST", tp)
    mob_screen_views.add(1, attributes={"screen": "Cart", "os": device["os"]})
    svc_analytics_event("add_to_cart", {"sku": "MAPP-001", "qty": 1}, tp)
    mob_screen_views.add(1, attributes={"screen": "Checkout", "os": device["os"]})
    return True, "1 item added to cart, checkout initiated"


def scen_full_checkout(session_id, customer, device):
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/checkout", "POST", tp)
    product_ids = [p["sku"] for p in random.sample(PRODUCTS, 2)]
    products, _, _ = svc_catalog_fetch(product_ids, gw_tp)
    warehouse = random.choice(WAREHOUSES)
    reservation_id, _ = svc_inventory_check(product_ids, warehouse, gw_tp)
    profile, _ = svc_profile_load(customer["id"], gw_tp)
    amount = sum(p["price"] for p in products)
    payment_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"
    ok, err, score, charge_id = svc_payment_charge(payment_id, customer, amount, tp)
    push_ok, _ = svc_push_notify(customer["id"], "order_confirmed", tp)
    svc_analytics_event("purchase", {"amount": amount, "items": len(products)}, tp)
    return ok, f"order placed ${amount:.2f}, charge={charge_id}"


def scen_track_order(session_id, customer, device):
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/orders/track", "GET", tp)
    mob_screen_views.add(1, attributes={"screen": "OrderTracking", "os": device["os"]})
    svc_analytics_event("order_track_view", {"session_id": session_id}, tp)
    return True, "order status refreshed from backend"


def scen_repeat_purchase(session_id, customer, device):
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/reorder", "POST", tp)
    product = random.choice(PRODUCTS)
    products, _, _ = svc_catalog_fetch([product["sku"]], gw_tp)
    warehouse = random.choice(WAREHOUSES)
    reservation_id, _ = svc_inventory_check([product["sku"]], warehouse, gw_tp)
    payment_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"
    ok, err, score, charge_id = svc_payment_charge(payment_id, customer, product["price"], tp)
    push_ok, _ = svc_push_notify(customer["id"], "order_confirmed", tp)
    return ok, f"1-tap reorder: {product['name']} ${product['price']:.2f}"


def scen_cellular_to_wifi(session_id, customer, device):
    # Start on cellular, then switch mid-session
    dev_cellular = {**device, "network": "cellular-lte"}
    tp = svc_mobile_app_launch(session_id, dev_cellular)
    gw_tp = svc_gateway_route(session_id, "/v2/browse", "GET", tp)
    product_ids = [p["sku"] for p in random.sample(PRODUCTS, 2)]
    products, _, _ = svc_catalog_fetch(product_ids, gw_tp)
    # Simulate network switch
    mob_network_req.record(random.uniform(200, 500), attributes={"network": "cellular-lte"})
    mob_network_req.record(random.uniform(20, 80),   attributes={"network": "wifi"})
    svc_analytics_event("network_switch", {"from": "cellular-lte", "to": "wifi"}, tp)
    return True, "browsed on cellular, switched to wifi mid-session"


def scen_guest_checkout_convert(session_id, customer, device):
    guest = {**CUSTOMERS[-1]}  # Guest user
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/checkout/guest", "POST", tp)
    product = random.choice(PRODUCTS)
    products, _, _ = svc_catalog_fetch([product["sku"]], gw_tp)
    # Guest checkout then account creation
    gw_tp2 = svc_gateway_route(session_id, "/v2/users/register", "POST", tp)
    svc_analytics_event("guest_convert", {"session_id": session_id}, tp)
    return True, "guest checkout → registered account created"


def scen_coupon_checkout(session_id, customer, device):
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/checkout/apply-coupon", "POST", tp)
    product = random.choice(PRODUCTS)
    products, _, _ = svc_catalog_fetch([product["sku"]], gw_tp)
    discount = round(product["price"] * 0.15, 2)
    final_price = round(product["price"] - discount, 2)
    svc_analytics_event("coupon_applied", {"code": "SAVE15", "discount": discount}, tp)
    payment_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"
    ok, err, score, charge_id = svc_payment_charge(payment_id, customer, final_price, tp)
    return ok, f"coupon SAVE15 applied: -${discount:.2f}, final ${final_price:.2f}"


def scen_gift_order_3ds(session_id, customer, device):
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/checkout/gift", "POST", tp)
    product = random.choice(PRODUCTS)
    products, _, _ = svc_catalog_fetch([product["sku"]], gw_tp)
    warehouse = random.choice(WAREHOUSES)
    reservation_id, _ = svc_inventory_check([product["sku"]], warehouse, gw_tp)
    payment_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"
    ok, err, score, charge_id = svc_payment_charge(payment_id, customer, product["price"], tp)
    push_ok, _ = svc_push_notify(customer["id"], "gift_order_confirmed", tp)
    svc_analytics_event("gift_order", {"recipient": "friend@email.com"}, tp)
    return ok, f"gift order: different shipping addr, 3DS challenge, charge={charge_id}"


def scen_partial_inventory(session_id, customer, device):
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/checkout", "POST", tp)
    product_ids = [p["sku"] for p in random.sample(PRODUCTS, 5)]
    products, _, _ = svc_catalog_fetch(product_ids, gw_tp)
    warehouse = random.choice(WAREHOUSES)
    # Partial: reserve 3, backorder 2
    reserved_ids = product_ids[:3]
    reservation_id, _ = svc_inventory_check(reserved_ids, warehouse, gw_tp)
    inv_stockouts.add(2, attributes={"warehouse": warehouse, "sku": "partial-backorder"})
    svc_analytics_event("partial_order", {"reserved": 3, "backordered": 2}, tp)
    return True, "5 products: 3 reserved, 2 backordered"


def scen_enterprise_bulk(session_id, customer, device):
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/checkout/bulk", "POST", tp)
    product_ids = [p["sku"] for p in PRODUCTS[:5]]
    products, _, _ = svc_catalog_fetch(product_ids, gw_tp)
    warehouse = random.choice(WAREHOUSES)
    reservation_id, _ = svc_inventory_check(product_ids, warehouse, gw_tp)
    profile, _ = svc_profile_load(customer["id"], gw_tp)
    amount = sum(p["price"] * 10 for p in products)
    discount = round(amount * 0.15, 2)
    final = round(amount - discount, 2)
    payment_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"
    ok, err, score, charge_id = svc_payment_charge(payment_id, customer, final, tp)
    push_ok, _ = svc_push_notify(customer["id"], "bulk_order_confirmed", tp)
    svc_analytics_event("bulk_order", {"amount": final, "discount": discount, "tier": "enterprise"}, tp)
    return ok, f"bulk 50 items, enterprise tier 15% discount, final=${final:.2f}"


# Error scenarios

def scen_fraud_blocked(session_id, customer, device):
    fraud_customer = next(c for c in CUSTOMERS if c["id"] == "MCUST-SUSP-001")
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/checkout", "POST", tp)
    product = random.choice(PRODUCTS)
    products, _, _ = svc_catalog_fetch([product["sku"]], gw_tp)
    payment_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"
    ok, err, score, charge_id = svc_payment_charge(payment_id, fraud_customer, product["price"], tp,
                                                     force_decline=False)
    # Force fraud via direct call
    score, decision, _ = svc_fraud_check(payment_id, fraud_customer, product["price"], tp, force_fraud=True)
    push_ok, _ = svc_push_notify(fraud_customer["id"], "payment_failed", tp)
    return False, f"fraud score {score:.2f} — payment blocked, push sent"


def scen_card_expired(session_id, customer, device):
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/checkout", "POST", tp)
    product = random.choice(PRODUCTS)
    products, _, _ = svc_catalog_fetch([product["sku"]], gw_tp)
    payment_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"
    ok, err, score, charge_id = svc_payment_charge(payment_id, customer, product["price"], tp,
                                                     force_decline=True)
    return False, f"402 from processor: {err} — user prompted to update card"


def scen_inventory_race(session_id, customer, device):
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/checkout", "POST", tp)
    low_stock_sku = "MAPP-006"  # inventory: 1
    products, _, _ = svc_catalog_fetch([low_stock_sku], gw_tp)
    warehouse = random.choice(WAREHOUSES)
    try:
        reservation_id, _ = svc_inventory_check([low_stock_sku], warehouse, gw_tp,
                                                  force_stockout=True)
        return True, "inventory reserved"
    except Exception as e:
        return False, f"inventory race: 2 users for last unit — stockout: {e}"


def scen_catalog_timeout_stale(session_id, customer, device):
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/product/MAPP-002", "GET", tp)
    product_ids = ["MAPP-002"]
    products, _, stale = svc_catalog_fetch(product_ids, gw_tp, force_timeout=True)
    mob_screen_views.add(1, attributes={"screen": "ProductDetail", "os": device["os"]})
    svc_analytics_event("catalog_stale_view", {"sku": "MAPP-002", "stale": True}, tp)
    return False, "catalog timeout: product detail slow, mobile showing stale cache"


def scen_push_token_expired(session_id, customer, device):
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/checkout", "POST", tp)
    product = random.choice(PRODUCTS)
    products, _, _ = svc_catalog_fetch([product["sku"]], gw_tp)
    payment_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"
    ok, err, score, charge_id = svc_payment_charge(payment_id, customer, product["price"], tp)
    # Push fails silently — order still succeeded
    push_ok, _ = svc_push_notify(customer["id"], "order_confirmed", tp, force_token_expired=True)
    return False, "APNs device token expired — push silent failure (order succeeded)"


def scen_profile_503_degradation(session_id, customer, device):
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/home-feed", "GET", tp)
    product_ids = [p["sku"] for p in random.sample(PRODUCTS, 3)]
    products, _, _ = svc_catalog_fetch(product_ids, gw_tp)
    profile, _ = svc_profile_load(customer["id"], gw_tp, force_503=True)
    svc_analytics_event("degraded_session", {"profile_available": False}, tp)
    return False, "profile service 503 — graceful degradation to guest mode"


def scen_network_retry(session_id, customer, device):
    tp = svc_mobile_app_launch(session_id, device)
    mob_network_req.record(random.uniform(2000, 5000), attributes={"network": device["network"], "attempt": "1"})
    mob_network_req.record(random.uniform(2000, 5000), attributes={"network": device["network"], "attempt": "2"})
    # Third attempt succeeds
    gw_tp = svc_gateway_route(session_id, "/v2/checkout", "POST", tp)
    mob_network_req.record(random.uniform(50, 200), attributes={"network": device["network"], "attempt": "3"})
    product = random.choice(PRODUCTS)
    products, _, _ = svc_catalog_fetch([product["sku"]], gw_tp)
    payment_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"
    ok, err, score, charge_id = svc_payment_charge(payment_id, customer, product["price"], tp)
    return ok, f"network loss during checkout: 3 retries, eventual {'success' if ok else 'failure'}"


def scen_app_crash_oom(session_id, customer, device):
    tp = svc_mobile_app_launch(session_id, device)
    gw_tp = svc_gateway_route(session_id, "/v2/product-gallery", "GET", tp)
    product_ids = [p["sku"] for p in PRODUCTS]
    # Simulate OOM during image loading — recorded as crash metric
    with mobile_client.tracer.start_as_current_span(
        "mobile.image.load_gallery", kind=SpanKind.CLIENT,
        context=extract_context(gw_tp),
        attributes={
            "mobile.screen.name": "ProductGallery",
            "mobile.images_requested": len(product_ids) * 3,
        }
    ) as crash_span:
        time.sleep(random.uniform(0.05, 0.1))
        oom_err = MemoryError("OOMKilled: heap allocation failed during image decoding — bitmap too large")
        crash_span.record_exception(oom_err, attributes={"exception.escaped": False})
        crash_span.set_status(StatusCode.ERROR, str(oom_err))
        crash_span.set_attribute("error.type", type(oom_err).__name__)
        mob_crashes.add(1, attributes={"crash.type": "OOMKill", "os": device["os"],
                                        "screen": "ProductGallery"})
        mobile_client.logger.error(
            "app crash: OOMKill during image gallery load",
            extra={"crash.type": "OOMKill", "device.model": device["model"],
                   "os.name": device["os"], "mobile.screen.name": "ProductGallery"}
        )
    return False, f"OOM crash during image loading — mobile.crashes +1"


# ── Scenario tables ───────────────────────────────────────────────────────────

HAPPY_SCENARIOS = [
    ("App launch + home feed",          scen_app_launch_home_feed),
    ("Search products + product detail",scen_search_products),
    ("Add to cart + checkout initiate", scen_add_to_cart_checkout),
    ("Full checkout + push notify",     scen_full_checkout),
    ("Track order status",              scen_track_order),
    ("Repeat purchase 1-tap",           scen_repeat_purchase),
    ("Cellular → wifi mid-session",     scen_cellular_to_wifi),
    ("Guest checkout → convert user",   scen_guest_checkout_convert),
    ("Coupon code + recalculate",       scen_coupon_checkout),
    ("Gift order + 3DS challenge",      scen_gift_order_3ds),
    ("Multi-item partial inventory",    scen_partial_inventory),
    ("Enterprise bulk order",           scen_enterprise_bulk),
]

ERROR_SCENARIOS = [
    ("Payment declined: fraud score 0.91",        scen_fraud_blocked),
    ("Card expired: 402 from processor",          scen_card_expired),
    ("Inventory race: stockout",                  scen_inventory_race),
    ("Catalog timeout: stale data served",        scen_catalog_timeout_stale),
    ("Push notification: APNs token expired",     scen_push_token_expired),
    ("Profile service 503: guest mode fallback",  scen_profile_503_degradation),
    ("Network loss: 3 retries, eventual success", scen_network_retry),
    ("App crash: OOM during image loading",       scen_app_crash_oom),
]

# ── Banner ────────────────────────────────────────────────────────────────────
print(f"\n{'='*62}")
print(f"EDOT-Autopilot | mobile-ecommerce-shopapp")
print(f"{'='*62}")

# ── Happy-path flows ──────────────────────────────────────────────────────────
print(f"\n-- Happy Path Flows --")
for label, fn in HAPPY_SCENARIOS:
    customer = random.choice([c for c in CUSTOMERS if c["tier"] != "guest"])
    device   = random.choice(DEVICES)
    try:
        ok, detail = run_scenario(label, customer, device, fn)
        check(f"[happy] {label}", ok, detail if not ok else "")
    except Exception as exc:
        check(f"[happy] {label}", False, str(exc))
    time.sleep(random.uniform(0.05, 0.15))

# ── Error / degraded flows ────────────────────────────────────────────────────
print(f"\n-- Error / Degraded Flows --")
for label, fn in ERROR_SCENARIOS:
    customer = random.choice(CUSTOMERS)
    device   = random.choice(DEVICES)
    try:
        ok, detail = run_scenario(label, customer, device, fn)
        # Error scenarios are expected failures — scenario completing is a PASS
        check(f"[error] {label}", True, detail)
    except Exception as exc:
        check(f"[error] {label}", False, str(exc))
    time.sleep(random.uniform(0.05, 0.15))

# ── Flush all telemetry providers ─────────────────────────────────────────────
for svc in [mobile_client, gateway, catalog_svc, inventory_svc, profile_svc,
            payment_svc, fraud_svc, processor_svc, push_svc, analytics_svc]:
    svc.flush()

# ── Span assertions: verify instrumentation correctness ──────────────────────
# Collect from all o11y instances in this test
all_spans = []
all_spans += mobile_client.get_finished_spans()
all_spans += gateway.get_finished_spans()
all_spans += catalog_svc.get_finished_spans()
all_spans += inventory_svc.get_finished_spans()
all_spans += profile_svc.get_finished_spans()
all_spans += payment_svc.get_finished_spans()
all_spans += fraud_svc.get_finished_spans()
all_spans += processor_svc.get_finished_spans()
all_spans += push_svc.get_finished_spans()
all_spans += analytics_svc.get_finished_spans()
print("\nSpan assertions:")
check("At least one span captured across all services",
      len(all_spans) > 0,
      f"got {len(all_spans)} total spans")
server_spans = [s for s in all_spans if s.kind.name == "SERVER"]
check("At least one SERVER span emitted",
      len(server_spans) > 0,
      f"got {len(server_spans)} SERVER spans")
attrs_with_gateway = [s for s in all_spans if s.attributes and "gateway.latency_ms" in s.attributes]
check("At least one span carries gateway.latency_ms attribute",
      len(attrs_with_gateway) > 0,
      f"got {len(attrs_with_gateway)} spans with gateway.latency_ms")
svc_names = {s.resource.attributes.get("service.name") for s in all_spans}
check("All 10 mobile ecommerce services emitted spans",
      len(svc_names) >= 10,
      f"services with spans: {svc_names}")

# ── Summary ───────────────────────────────────────────────────────────────────
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
