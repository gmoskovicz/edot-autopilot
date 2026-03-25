#!/usr/bin/env python3
"""
Smoke test: Tier D — Delphi / Object Pascal (sidecar simulation).

Simulates a Delphi POS application submitting observability via the HTTP sidecar.
Business scenario: point-of-sale transaction processing — barcode scan, inventory
lookup, payment processing, receipt printing, end-of-day Z-report.

Run:
    cd smoke-tests && python3 45-tier-d-delphi/smoke.py
"""

import os, sys, time, random, uuid
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-d-delphi"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

transactions_processed = meter.create_counter("delphi.transactions")
transaction_value      = meter.create_histogram("delphi.transaction_value_usd", unit="USD")
payment_duration       = meter.create_histogram("delphi.payment_duration_ms", unit="ms")
items_scanned          = meter.create_counter("delphi.items_scanned")

TRANSACTIONS = [
    {"terminal": "POS-04", "items": [
        {"barcode": "4011200296908", "name": "Organic Bananas",    "qty": 2, "price": 1.49},
        {"barcode": "0099482408345", "name": "Greek Yogurt 500g",  "qty": 1, "price": 3.79},
        {"barcode": "0078742265834", "name": "Sparkling Water 6pk","qty": 1, "price": 4.99},
    ], "payment": "credit_card"},
    {"terminal": "POS-07", "items": [
        {"barcode": "0028400054386", "name": "Lay's Classic 285g", "qty": 3, "price": 4.49},
        {"barcode": "0016000275263", "name": "Cheerios 510g",      "qty": 1, "price": 5.29},
    ], "payment": "contactless_nfc"},
    {"terminal": "POS-01", "items": [
        {"barcode": "4002103198627", "name": "AA Batteries 8pk",   "qty": 2, "price": 8.99},
        {"barcode": "0071100006947", "name": "USB-C Cable 1m",     "qty": 1, "price": 12.99},
        {"barcode": "0012000161155", "name": "Energy Drink 500ml", "qty": 4, "price": 2.49},
    ], "payment": "debit_card", "discount_pct": 0.10},
]

def process_transaction(txn):
    tx_id   = f"TXN-{uuid.uuid4().hex[:10].upper()}"
    subtotal = sum(i["qty"] * i["price"] for i in txn["items"])
    discount = subtotal * txn.get("discount_pct", 0)
    tax      = (subtotal - discount) * 0.085
    total    = subtotal - discount + tax
    t0 = time.time()

    with tracer.start_as_current_span("Delphi.TTransactionForm.ProcessSale", kind=SpanKind.INTERNAL,
            attributes={"delphi.form": "TTransactionForm", "delphi.method": "ProcessSale",
                        "pos.terminal_id": txn["terminal"], "pos.tx_id": tx_id,
                        "pos.item_count": len(txn["items"]),
                        "pos.payment_method": txn["payment"]}) as span:

        for item in txn["items"]:
            with tracer.start_as_current_span("Delphi.TBarcodeScanner.LookupSKU", kind=SpanKind.CLIENT,
                    attributes={"pos.barcode": item["barcode"], "db.system": "firebird",
                                "db.operation": "SELECT"}):
                time.sleep(random.uniform(0.002, 0.008))
                items_scanned.add(item["qty"], attributes={"pos.terminal_id": txn["terminal"]})

        with tracer.start_as_current_span("Delphi.TPaymentGateway.Authorize", kind=SpanKind.CLIENT,
                attributes={"payment.method": txn["payment"], "payment.amount_usd": round(total, 2),
                            "payment.network": "Verifone"}) as s:
            t_pay = time.time()
            time.sleep(random.uniform(0.15, 0.60))
            auth_code = f"AUTH{random.randint(100000, 999999)}"
            s.set_attribute("payment.auth_code",   auth_code)
            s.set_attribute("payment.approved",    True)
            pay_dur = (time.time() - t_pay) * 1000
            payment_duration.record(pay_dur, attributes={"payment.method": txn["payment"]})

        with tracer.start_as_current_span("Delphi.TReceiptPrinter.PrintReceipt", kind=SpanKind.CLIENT,
                attributes={"printer.device": "Epson-TM-T88VII", "printer.lines": len(txn["items"]) + 8}):
            time.sleep(random.uniform(0.04, 0.10))

        with tracer.start_as_current_span("Delphi.TDatabase.CommitTransaction", kind=SpanKind.CLIENT,
                attributes={"db.system": "firebird", "db.operation": "COMMIT"}):
            time.sleep(random.uniform(0.005, 0.015))

        dur = (time.time() - t0) * 1000
        span.set_attribute("pos.subtotal_usd", round(subtotal, 2))
        span.set_attribute("pos.discount_usd", round(discount, 2))
        span.set_attribute("pos.tax_usd",      round(tax, 2))
        span.set_attribute("pos.total_usd",    round(total, 2))

        transactions_processed.add(1, attributes={"pos.terminal_id": txn["terminal"],
                                                   "payment.method": txn["payment"]})
        transaction_value.record(total, attributes={"pos.terminal_id": txn["terminal"]})

        logger.info("POS transaction complete",
                    extra={"pos.terminal_id": txn["terminal"], "pos.tx_id": tx_id,
                           "pos.total_usd": round(total, 2), "pos.item_count": len(txn["items"]),
                           "payment.method": txn["payment"]})
    return tx_id, total

print(f"\n[{SVC}] Simulating Delphi POS transaction processing...")
for txn in TRANSACTIONS:
    tx_id, total = process_transaction(txn)
    disc = f" -{txn.get('discount_pct',0)*100:.0f}%" if txn.get("discount_pct") else ""
    print(f"  ✅ {tx_id}  {txn['terminal']}  items={len(txn['items'])}  total=${total:.2f}{disc}  {txn['payment']}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
