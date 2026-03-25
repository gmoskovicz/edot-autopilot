#!/usr/bin/env python3
"""
Smoke test: Tier C — slack-sdk WebClient (monkey-patched).

Patches WebClient.chat_postMessage and chat_postEphemeral.
Business scenario: Incident alerting — SLA breach triggers Slack alerts
to #ops-alerts, follow-up thread to #on-call.

Run:
    cd smoke-tests && python3 31-tier-c-slack/smoke.py
"""

import os, sys, uuid, time, random
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-c-slack"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

slack_msgs   = meter.create_counter("slack.messages_sent")
slack_latency= meter.create_histogram("slack.send_ms", unit="ms")
alert_counter= meter.create_counter("slack.alerts_fired")


class _MockSlackResponse:
    def __init__(self):
        self.data = {"ok": True, "ts": f"{time.time():.6f}", "channel": "C123456",
                     "message": {"ts": f"{time.time():.6f}"}}
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


_orig_post      = _MockWebClient.chat_postMessage
_orig_ephemeral = _MockWebClient.chat_postEphemeral

def _inst_post(self, channel, text=None, blocks=None, thread_ts=None, **kwargs):
    t0 = time.time()
    with tracer.start_as_current_span("slack.chat_postMessage", kind=SpanKind.CLIENT,
        attributes={"slack.channel":     channel,
                    "slack.has_blocks":  blocks is not None,
                    "slack.is_thread":   thread_ts is not None,
                    "messaging.system":  "slack"}) as span:
        try:
            resp = _orig_post(self, channel, text, blocks, thread_ts, **kwargs)
            dur  = (time.time() - t0) * 1000
            span.set_attribute("slack.message_ts", resp.get("ts", ""))
            slack_msgs.add(1, attributes={"slack.channel": channel})
            slack_latency.record(dur, attributes={"slack.channel": channel})
            logger.info("slack message sent",
                        extra={"slack.channel": channel, "slack.message_ts": resp.get("ts", ""),
                               "slack.is_thread": thread_ts is not None})
            return resp
        except Exception as e:
            span.set_status(StatusCode.ERROR, str(e))
            logger.error("slack message failed",
                         extra={"slack.channel": channel, "error.message": str(e)})
            raise

_MockWebClient.chat_postMessage = _inst_post


def fire_sla_alert(incident_id, service, sla_type, severity, breach_duration_min):
    client = slack_sdk.WebClient(token="xoxb-fake-token")
    alert_counter.add(1, attributes={"alert.severity": severity, "alert.sla_type": sla_type})

    resp = client.chat_postMessage(
        channel="#ops-alerts",
        text=f"🚨 SLA Breach: {service} — {sla_type} ({severity})",
        blocks=[{"type": "section", "text": {"type": "mrkdwn",
                 "text": f"*Incident:* `{incident_id}`\n*Service:* {service}\n"
                         f"*SLA:* {sla_type}\n*Severity:* {severity}\n"
                         f"*Breach duration:* {breach_duration_min}m"}}],
    )
    client.chat_postMessage(
        channel="#on-call",
        text=f"⚠️ {incident_id}: {service} SLA breach assigned",
        thread_ts=resp.get("ts"),
    )
    logger.warning("SLA breach alert fired",
                   extra={"incident.id": incident_id, "alert.service": service,
                          "alert.sla_type": sla_type, "alert.severity": severity,
                          "alert.breach_duration_min": breach_duration_min})
    return resp


incidents = [
    ("INC-001", "payment-api",      "response_time_p99", "critical", 12),
    ("INC-002", "checkout-service", "error_rate",        "warning",  3),
    ("INC-003", "inventory-db",     "availability",      "critical", 45),
]

print(f"\n[{SVC}] Firing incident alerts via patched slack-sdk...")
for inc_id, service, sla, severity, duration in incidents:
    try:
        fire_sla_alert(inc_id, service, sla, severity, duration)
        icon = "🚨" if severity == "critical" else "⚠️ "
        print(f"  {icon} {inc_id}  {service:<25}  {sla:<25}  {severity}")
    except Exception as e:
        print(f"  🚫 {inc_id}  error={e}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
