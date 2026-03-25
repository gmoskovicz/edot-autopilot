"""
Incident Alerting — Slack via slack-sdk

No observability. Run `Observe this project.` to add it.
"""

import time
import random
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING)


# ── Mock slack-sdk (simulates real WebClient without a Slack token) ────────────

class _MockSlackResponse:
    def __init__(self):
        self.data = {
            "ok": True,
            "ts": f"{time.time():.6f}",
            "channel": "C123456",
            "message": {"ts": f"{time.time():.6f}"},
        }

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)


class _MockWebClient:
    def __init__(self, token=None):
        self.token = token

    def chat_postMessage(self, channel, text=None, blocks=None, thread_ts=None, **kwargs):
        time.sleep(random.uniform(0.03, 0.08))
        if random.random() < 0.02:
            raise Exception("slack_sdk.errors.SlackApiError: not_in_channel")
        return _MockSlackResponse()

    def chat_postEphemeral(self, channel, user, text=None, **kwargs):
        time.sleep(0.02)
        return _MockSlackResponse()


class slack_sdk:
    WebClient = _MockWebClient


# ── Application code ───────────────────────────────────────────────────────────

def fire_sla_alert(incident_id, service, sla_type, severity, breach_duration_min):
    """Send an SLA breach alert to #ops-alerts and a follow-up to #on-call."""
    client = slack_sdk.WebClient(token="xoxb-fake-token")

    resp = client.chat_postMessage(
        channel="#ops-alerts",
        text=f"SLA Breach: {service} — {sla_type} ({severity})",
        blocks=[{
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Incident:* `{incident_id}`\n*Service:* {service}\n"
                    f"*SLA:* {sla_type}\n*Severity:* {severity}\n"
                    f"*Breach duration:* {breach_duration_min}m"
                ),
            },
        }],
    )

    client.chat_postMessage(
        channel="#on-call",
        text=f"{incident_id}: {service} SLA breach assigned",
        thread_ts=resp.get("ts"),
    )

    logger.warning("SLA breach alert fired",
                   extra={"incident.id": incident_id, "alert.service": service,
                          "alert.sla_type": sla_type, "alert.severity": severity,
                          "alert.breach_duration_min": breach_duration_min})
    return resp


if __name__ == "__main__":
    incidents = [
        ("INC-001", "payment-api",      "response_time_p99", "critical", 12),
        ("INC-002", "checkout-service", "error_rate",        "warning",  3),
        ("INC-003", "inventory-db",     "availability",      "critical", 45),
    ]

    for inc_id, service, sla, severity, duration in incidents:
        try:
            fire_sla_alert(inc_id, service, sla, severity, duration)
            print(f"Alert fired: {inc_id} / {service} / {severity}")
        except Exception as e:
            print(f"Alert failed: {inc_id}: {e}")
