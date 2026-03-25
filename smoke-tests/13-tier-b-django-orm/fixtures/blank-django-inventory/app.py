"""
Inventory Reorder Service — Django Management Command

No observability. Run `Observe this project.` to add it.
"""

import os
import uuid
import logging

import django
from django.conf import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Minimal Django configuration (no actual database) ─────────────────────────
if not settings.configured:
    settings.configure(
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            }
        },
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
        ],
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
    )
    django.setup()


# ── Mock Django ORM models (no real DB migrations needed) ─────────────────────
class _ProductQuerySet:
    """Simulates Django QuerySet.filter() for low-stock products."""

    def filter(self, **kwargs):
        return [
            {
                "sku": "SKU-A1001",
                "name": "Widget Pro",
                "stock": 3,
                "reorder_at": 10,
                "reorder_qty": 100,
                "unit_cost": 12.50,
                "supplier": "SUP-001",
            },
            {
                "sku": "SKU-B2002",
                "name": "Gadget Plus",
                "stock": 1,
                "reorder_at": 5,
                "reorder_qty": 50,
                "unit_cost": 45.00,
                "supplier": "SUP-002",
            },
            {
                "sku": "SKU-C3003",
                "name": "Component X",
                "stock": 0,
                "reorder_at": 20,
                "reorder_qty": 200,
                "unit_cost": 3.75,
                "supplier": "SUP-001",
            },
        ]


class Product:
    objects = _ProductQuerySet()


class PurchaseOrder:
    @staticmethod
    def objects_create(product_sku, supplier_id, quantity, unit_cost):
        """Simulate Model.objects.create() — writes PO to DB."""
        return {
            "po_id": f"PO-{uuid.uuid4().hex[:8].upper()}",
            "product_sku": product_sku,
            "supplier_id": supplier_id,
            "quantity": quantity,
            "unit_cost": unit_cost,
            "total_cost": quantity * unit_cost,
            "status": "submitted",
        }


# ── Django management command: handle_reorders ────────────────────────────────
def handle_reorders():
    """
    Management command that finds products below reorder threshold and creates
    purchase orders for each one.

    In production this runs via: python manage.py handle_reorders
    """
    logger.info("Starting inventory reorder management command")

    # Query: find all products with stock below their reorder threshold
    low_stock_products = Product.objects.filter(stock__lt="reorder_at")
    logger.info(f"Found {len(low_stock_products)} products below reorder threshold")

    orders_created = 0
    total_value = 0.0
    created_orders = []

    for product in low_stock_products:
        qty = product["reorder_qty"]
        value = qty * product["unit_cost"]
        total_value += value

        # Create a purchase order for this product
        po = PurchaseOrder.objects_create(
            product_sku=product["sku"],
            supplier_id=product["supplier"],
            quantity=qty,
            unit_cost=product["unit_cost"],
        )
        orders_created += 1
        created_orders.append(po)

        logger.info(
            f"Purchase order created: {po['po_id']} for {product['sku']}",
            extra={
                "po_id": po["po_id"],
                "product_sku": product["sku"],
                "supplier_id": product["supplier"],
                "reorder_qty": qty,
                "po_value_usd": value,
            },
        )

    logger.info(
        f"Reorder command complete: {orders_created} POs created, "
        f"total value ${total_value:.2f}",
        extra={
            "orders_created": orders_created,
            "total_value_usd": round(total_value, 2),
        },
    )
    return orders_created, total_value, created_orders


if __name__ == "__main__":
    orders_created, total_value, orders = handle_reorders()
    print(f"Created {orders_created} purchase orders, total value: ${total_value:.2f}")
    for po in orders:
        print(f"  {po['po_id']}: {po['quantity']} x {po['product_sku']} "
              f"@ ${po['unit_cost']:.2f} = ${po['total_cost']:.2f}")
