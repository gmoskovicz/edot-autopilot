"""
SMS Alert Service — Twilio SDK

No observability. Run `Observe this project.` to add it.

This service sends appointment reminder SMS messages using the Twilio REST API.
It is used by a healthcare scheduling platform to notify patients of upcoming
appointments. Every failed SMS is a missed patient touchpoint.
"""

import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Simulated Twilio client (real usage: from twilio.rest import Client)
# In production this would be:
#   client = Client(account_sid, auth_token)
#   client.messages.create(to=..., from_=..., body=...)

class _MockMessages:
    """Simulates twilio.rest.Client.messages — same interface as the real SDK."""
    @staticmethod
    def create(to, from_, body, **kwargs):
        import uuid
        logger.info(f"SMS to {to}: {body[:40]}...")
        return type("Message", (), {
            "sid":    f"SM{uuid.uuid4().hex}",
            "status": "queued",
            "to":     to,
            "from_":  from_,
            "body":   body[:20],
        })()


class Client:
    """Drop-in replacement for twilio.rest.Client."""
    messages = _MockMessages()


def send_appointment_reminder(patient_phone: str, patient_name: str,
                               appt_time: str, clinic: str) -> dict:
    """Send a reminder SMS. Returns message details."""
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "ACtest")
    auth_token  = os.environ.get("TWILIO_AUTH_TOKEN", "test")
    from_number = os.environ.get("TWILIO_FROM_NUMBER", "+18005550100")

    client = Client()
    msg = client.messages.create(
        to=patient_phone,
        from_=from_number,
        body=f"Hi {patient_name}, reminder: appointment at {clinic} on {appt_time}. "
             f"Reply STOP to opt out.",
    )
    logger.info(f"Reminder sent sid={msg.sid} to={patient_phone}")
    return {"sid": msg.sid, "status": msg.status, "to": patient_phone}


def send_bulk_reminders(reminders: list) -> list:
    """Send reminders to a batch of patients. Returns results list."""
    results = []
    for patient_phone, patient_name, appt_time, clinic in reminders:
        try:
            result = send_appointment_reminder(patient_phone, patient_name,
                                               appt_time, clinic)
            results.append({"success": True, **result})
        except Exception as e:
            logger.error(f"Failed to send to {patient_phone}: {e}")
            results.append({"success": False, "to": patient_phone, "error": str(e)})
    return results


DAILY_REMINDERS = [
    ("+12125550101", "Alice Chen",    "2026-03-26 10:00", "Downtown Medical"),
    ("+13105550102", "Bob Martinez",  "2026-03-26 14:30", "Westside Clinic"),
    ("+16175550103", "Carol Johnson", "2026-03-27 09:00", "North Health"),
    ("+17185550104", "David Kim",     "2026-03-27 11:15", "Downtown Medical"),
    ("+19175550105", "Eve Patel",     "2026-03-28 16:00", "Eastside Health"),
]

if __name__ == "__main__":
    logger.info("Starting daily appointment reminder batch")
    results = send_bulk_reminders(DAILY_REMINDERS)
    sent    = sum(1 for r in results if r["success"])
    failed  = sum(1 for r in results if not r["success"])
    logger.info(f"Batch complete: {sent} sent, {failed} failed")
