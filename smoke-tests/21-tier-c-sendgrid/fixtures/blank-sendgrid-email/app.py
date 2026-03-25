"""
Email Notification Service — SendGrid API

No observability. Run `Observe this project.` to add it.
"""

import os
import logging

import sendgrid
from sendgrid.helpers.mail import Mail

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "noreply@company.com")


# ── Email sending functions ────────────────────────────────────────────────────

def send_password_reset(user_email: str, reset_token: str) -> dict:
    """
    Send a password reset email to a user.
    Called from the /auth/forgot-password endpoint.
    """
    sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=user_email,
        subject="Reset your password",
        html_content=(
            f"<p>Click the link below to reset your password.</p>"
            f"<p><a href='https://app.company.com/reset?token={reset_token}'>"
            f"Reset Password</a></p>"
        ),
    )
    message.template_id = "d-password-reset-v2"

    response = sg.send(message)
    logger.info(
        f"Password reset email sent to {user_email}",
        extra={
            "email_to": user_email,
            "template_id": "d-password-reset-v2",
            "status_code": response.status_code,
        },
    )
    return {"status": "sent", "status_code": response.status_code}


def send_welcome_email(user_email: str, plan: str, first_name: str) -> dict:
    """
    Send a welcome email when a new user signs up.
    Called from the /auth/signup endpoint.
    """
    sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
    message = Mail(
        from_email="welcome@company.com",
        to_emails=user_email,
        subject=f"Welcome to your {plan} plan, {first_name}!",
        html_content=(
            f"<p>Hi {first_name},</p>"
            f"<p>Welcome! You're now on the <strong>{plan}</strong> plan.</p>"
            f"<p>Get started at <a href='https://app.company.com'>app.company.com</a></p>"
        ),
    )
    message.template_id = "d-welcome-v3"

    response = sg.send(message)
    logger.info(
        f"Welcome email sent to {user_email} (plan={plan})",
        extra={
            "email_to": user_email,
            "plan": plan,
            "template_id": "d-welcome-v3",
            "status_code": response.status_code,
        },
    )
    return {"status": "sent", "status_code": response.status_code}


def send_invoice_email(user_email: str, invoice_id: str, amount_usd: float) -> dict:
    """
    Send an invoice notification email. Called monthly by the billing job.
    """
    sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
    message = Mail(
        from_email="billing@company.com",
        to_emails=user_email,
        subject=f"Your invoice #{invoice_id} for ${amount_usd:.2f}",
        html_content=(
            f"<p>Your invoice #{invoice_id} for ${amount_usd:.2f} is ready.</p>"
            f"<p><a href='https://app.company.com/invoices/{invoice_id}'>View Invoice</a></p>"
        ),
    )
    message.template_id = "d-invoice-v1"

    response = sg.send(message)
    logger.info(
        f"Invoice email sent to {user_email} invoice={invoice_id}",
        extra={
            "email_to": user_email,
            "invoice_id": invoice_id,
            "amount_usd": amount_usd,
            "template_id": "d-invoice-v1",
            "status_code": response.status_code,
        },
    )
    return {"status": "sent", "status_code": response.status_code}


# ── Sample run (used in local dev / smoke test) ───────────────────────────────
if __name__ == "__main__":
    # These calls will fail without a real API key — that is expected
    test_cases = [
        ("password_reset", "alice@enterprise.com"),
        ("password_reset", "bob@startup.io"),
        ("welcome",        "carol@personal.net"),
        ("invoice",        "dave@bigcorp.com"),
    ]

    for email_type, email in test_cases:
        try:
            if email_type == "password_reset":
                result = send_password_reset(email, "tok_abc123")
            elif email_type == "welcome":
                result = send_welcome_email(email, "pro", "Carol")
            elif email_type == "invoice":
                result = send_invoice_email(email, "INV-2024-001", 299.00)
            print(f"  {email_type}: {email} → {result['status']}")
        except Exception as e:
            print(f"  {email_type}: {email} → ERROR: {e}")
