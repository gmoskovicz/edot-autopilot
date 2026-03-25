#!/usr/bin/env python3
"""
Smoke test: Tier B — Django ORM (no EDOT middleware, management command pattern).

Django management commands run outside the request/response cycle — no
auto-instrumentation fires. We wrap the ORM calls manually.

Business scenario: Inventory reorder — find products below reorder threshold,
create purchase orders, record supplier confirmation.

Run:
    cd smoke-tests && python3 13-tier-b-django-orm/smoke.py
"""

import os, sys, uuid, random, time
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-b-django-orm"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

po_created   = meter.create_counter("inventory.purchase_orders_created")
reorder_qty  = meter.create_histogram("inventory.reorder_quantity", unit="units")
po_value     = meter.create_histogram("inventory.purchase_order_value_usd", unit="USD")


# ── Mock Django ORM (no database needed) ──────────────────────────────────────
class Product:
    objects = None  # patched below

class _ProductManager:
    def filter(self, **kwargs):
        """Simulate QuerySet.filter() returning low-stock products."""
        return [
            {"sku": "SKU-A1001", "name": "Widget Pro",    "stock": 3,  "reorder_at": 10, "reorder_qty": 100, "unit_cost": 12.50, "supplier": "SUP-001"},
            {"sku": "SKU-B2002", "name": "Gadget Plus",   "stock": 1,  "reorder_at": 5,  "reorder_qty": 50,  "unit_cost": 45.00, "supplier": "SUP-002"},
            {"sku": "SKU-C3003", "name": "Component X",   "stock": 0,  "reorder_at": 20, "reorder_qty": 200, "unit_cost": 3.75,  "supplier": "SUP-001"},
        ]

Product.objects = _ProductManager()


class PurchaseOrder:
    @staticmethod
    def save_new(product, qty):
        """Simulate Model.save() — writes PO to DB."""
        return {"po_id": f"PO-{uuid.uuid4().hex[:8].upper()}", "status": "submitted"}


# ── Tier B: instrument the ORM calls ─────────────────────────────────────────
def _instrumented_filter(**kwargs):
    with tracer.start_as_current_span("django.orm.filter", kind=SpanKind.CLIENT,
        attributes={"db.system": "django-orm", "db.model": "Product",
                    "orm.filter_kwargs": str(kwargs)}) as span:
        results = Product.objects.__class__().filter(**kwargs)
        span.set_attribute("orm.result_count", len(results))
        return results

def _instrumented_save(product, qty):
    with tracer.start_as_current_span("django.orm.save", kind=SpanKind.CLIENT,
        attributes={"db.system": "django-orm", "db.model": "PurchaseOrder",
                    "po.product_sku": product["sku"], "po.quantity": qty}) as span:
        result = PurchaseOrder.save_new(product, qty)
        span.set_attribute("po.id",     result["po_id"])
        span.set_attribute("po.status", result["status"])
        return result


# ── Management command: handle_reorders ───────────────────────────────────────
def handle_reorders():
    with tracer.start_as_current_span("management.handle_reorders", kind=SpanKind.SERVER,
        attributes={"command": "handle_reorders", "app": "inventory"}) as span:

        logger.info("starting inventory reorder management command",
                    extra={"command": "handle_reorders"})

        low_stock = _instrumented_filter(stock__lt=10)
        span.set_attribute("inventory.products_below_threshold", len(low_stock))

        total_value, orders_created = 0.0, 0
        for product in low_stock:
            qty      = product["reorder_qty"]
            value    = qty * product["unit_cost"]
            total_value += value

            po = _instrumented_save(product, qty)
            orders_created += 1

            po_created.add(1, attributes={"supplier.id": product["supplier"]})
            reorder_qty.record(qty,   attributes={"product.sku": product["sku"]})
            po_value.record(value,    attributes={"supplier.id": product["supplier"]})

            logger.info("purchase order created",
                        extra={"po.id": po["po_id"], "product.sku": product["sku"],
                               "reorder.quantity": qty, "po.value_usd": value,
                               "supplier.id": product["supplier"]})

            print(f"  ✅ {po['po_id']}  {product['sku']}  qty={qty}  "
                  f"${value:.2f}  supplier={product['supplier']}")

        span.set_attribute("reorder.orders_created",  orders_created)
        span.set_attribute("reorder.total_value_usd", round(total_value, 2))

        logger.info("reorder command complete",
                    extra={"reorder.orders_created": orders_created,
                           "reorder.total_value_usd": round(total_value, 2)})


print(f"\n[{SVC}] Simulating Django ORM management command → reorder check...")
handle_reorders()
o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
