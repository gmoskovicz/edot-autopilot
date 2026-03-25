"""
Monthly Invoice Generation — Celery Task Worker

No observability. Run `Observe this project.` to add it.

Background task worker that generates PDF invoices, emails them to customers,
and records delivery confirmation. Runs as a monthly billing batch.

In production this is invoked by: celery -A app worker -Q billing
"""

import uuid
import time
import random
import logging

from celery import Celery

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Celery app — broker URL comes from env (Redis in prod, memory transport in dev)
import os
BROKER_URL = os.environ.get("CELERY_BROKER_URL", "memory://")
app = Celery("billing", broker=BROKER_URL)
app.conf.task_always_eager = True  # Run tasks synchronously for local dev


@app.task(name="billing.generate_invoice", queue="billing")
def generate_invoice(customer_id: str, billing_period: str, amount: float) -> dict:
    """
    Generate and dispatch a monthly invoice.

    Args:
        customer_id:     Customer account identifier (e.g. 'CUST-ENT-001')
        billing_period:  Month string (e.g. '2026-02')
        amount:          Invoice total in USD

    Returns:
        dict with invoice_id (str) and delivered (bool)
    """
    invoice_id = f"INV-{uuid.uuid4().hex[:8].upper()}"

    # Step 1: Generate PDF
    _generate_pdf(invoice_id, customer_id, amount)

    # Step 2: Send email
    delivered = _send_invoice_email(invoice_id, customer_id)

    logger.info(
        "invoice generated and dispatched",
        extra={"invoice_id": invoice_id, "customer_id": customer_id,
               "invoice_amount_usd": amount, "billing_period": billing_period,
               "email_delivered": delivered},
    )
    return {"invoice_id": invoice_id, "delivered": delivered}


def _generate_pdf(invoice_id: str, customer_id: str, amount: float) -> dict:
    """Render the invoice as a PDF. Returns metadata about the generated file."""
    time.sleep(0.03)  # simulated PDF render time
    pages  = random.randint(1, 4)
    logger.info(
        "invoice PDF generated",
        extra={"invoice_id": invoice_id, "customer_id": customer_id,
               "invoice_amount_usd": amount, "pdf_pages": pages},
    )
    return {"pages": pages, "format": "pdf"}


def _send_invoice_email(invoice_id: str, customer_id: str) -> bool:
    """Send the invoice PDF via email. Returns True if delivered successfully."""
    time.sleep(0.02)  # simulated email gateway latency
    delivered = random.random() > 0.05  # 5% bounce rate
    if not delivered:
        logger.warning(
            "invoice email bounced",
            extra={"invoice_id": invoice_id, "customer_id": customer_id,
                   "email_provider": "sendgrid"},
        )
    else:
        logger.info(
            "invoice email delivered",
            extra={"invoice_id": invoice_id, "customer_id": customer_id,
                   "email_provider": "sendgrid"},
        )
    return delivered


@app.task(name="billing.send_payment_reminder", queue="billing")
def send_payment_reminder(customer_id: str, invoice_id: str,
                           days_overdue: int, amount: float) -> dict:
    """
    Send a payment reminder for an overdue invoice.

    Args:
        customer_id:  Customer account identifier
        invoice_id:   Invoice that is overdue
        days_overdue: How many days past the due date
        amount:       Outstanding amount in USD

    Returns:
        dict with reminder_id and channel used
    """
    time.sleep(0.02)
    reminder_id = f"REM-{uuid.uuid4().hex[:8].upper()}"
    channel     = "email" if days_overdue < 14 else "phone"

    logger.warning(
        "payment reminder sent",
        extra={"customer_id": customer_id, "invoice_id": invoice_id,
               "days_overdue": days_overdue, "amount_usd": amount,
               "reminder_id": reminder_id, "channel": channel},
    )
    return {"reminder_id": reminder_id, "channel": channel}


if __name__ == "__main__":
    # Quick local smoke run
    result = generate_invoice("CUST-ENT-001", "2026-02", 4200.00)
    print(f"generate_invoice: {result}")
    result = send_payment_reminder("CUST-FREE-007", "INV-DEADBEEF", 5, 29.99)
    print(f"send_payment_reminder: {result}")
