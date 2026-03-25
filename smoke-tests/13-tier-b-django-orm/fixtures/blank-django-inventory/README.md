# Inventory Reorder Service

A Django management command that automates inventory reordering. It queries
products below their reorder threshold and creates purchase orders for each.

## Key flows

- `handle_reorders()` — The management command entry point. Calls
  `Product.objects.filter(stock__lt=reorder_at)` to find low-stock items,
  then calls `PurchaseOrder.objects_create(...)` for each one.
- Each purchase order records: product SKU, supplier ID, quantity, unit cost,
  and total cost.
- Runs outside the HTTP request/response cycle (no WSGI/ASGI auto-instrumentation fires).

## Business context

Products have a `reorder_at` threshold and a `reorder_qty`. When stock drops
below the threshold, a purchase order is automatically submitted to the
supplier. The command tracks total reorder value for financial reporting.

Typical inventory: 3 products go below threshold per daily run. Total PO
value is around $3,500–$5,000 per run.

## Stack

- Django 4.x — ORM + management commands
- SQLite (dev) / PostgreSQL (prod) — product and PO storage

## No observability yet

This service has zero OpenTelemetry instrumentation. The management command
runs outside the request lifecycle, so Django auto-instrumentation won't fire.

The agent should apply Tier B (manual wrapping): wrap the ORM calls
(`Product.objects.filter`, `PurchaseOrder.objects_create`) with explicit spans,
and wrap the outer `handle_reorders` function with a SERVER span.

Expected spans:
- `management.handle_reorders` (SERVER) — covers the full command
- `django.orm.filter` (CLIENT) — low-stock query with `db.system=django-orm`
- `django.orm.save` (CLIENT) — one per purchase order, with `po.product_sku`,
  `po.quantity`, `po.value_usd`
