#!/usr/bin/env python3
"""
Smoke test: Tier C — OpenAI Python SDK (monkey-patched).

Patches openai.ChatCompletion.create — existing call sites unchanged.
Business scenario: Customer support ticket classification — classify incoming
tickets by severity and category using GPT.

Run:
    cd smoke-tests && python3 32-tier-c-openai/smoke.py
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

SVC = "smoke-tier-c-openai"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

ai_requests    = meter.create_counter("openai.requests")
ai_tokens      = meter.create_histogram("openai.total_tokens")
ai_latency     = meter.create_histogram("openai.response_ms", unit="ms")
ai_cost_est    = meter.create_histogram("openai.estimated_cost_usd", unit="USD")

CATEGORIES = ["billing", "technical", "account", "feature-request", "compliance"]
SEVERITIES = ["low", "medium", "high", "critical"]


class _MockChoice:
    def __init__(self, content):
        self.message = type("Msg", (), {"content": content, "role": "assistant"})()

class _MockCompletion:
    def __init__(self, model, prompt_tokens, completion_tokens, content):
        self.id      = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        self.model   = model
        self.choices = [_MockChoice(content)]
        self.usage   = type("Usage", (), {
            "prompt_tokens":     prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens":      prompt_tokens + completion_tokens,
        })()

class _MockChatCompletion:
    @staticmethod
    def create(model, messages, temperature=0.7, max_tokens=150, **kwargs):
        time.sleep(random.uniform(0.2, 0.8))  # realistic LLM latency
        prompt_tokens     = sum(len(m["content"].split()) * 1.3 for m in messages)
        completion_tokens = random.randint(20, 80)
        category  = random.choice(CATEGORIES)
        severity  = random.choice(SEVERITIES)
        content   = f'{{"category": "{category}", "severity": "{severity}", "confidence": {random.uniform(0.75, 0.99):.2f}}}'
        return _MockCompletion(model, int(prompt_tokens), completion_tokens, content)

class openai:
    ChatCompletion = _MockChatCompletion
    api_key = "sk-fake-key-for-smoke-test"


_orig_create = _MockChatCompletion.create

@staticmethod
def _inst_create(model, messages, temperature=0.7, max_tokens=150, **kwargs):
    t0 = time.time()
    with tracer.start_as_current_span("openai.chat_completion", kind=SpanKind.CLIENT,
        attributes={"llm.provider":         "openai",
                    "llm.model":            model,
                    "llm.temperature":      temperature,
                    "llm.max_tokens":       max_tokens,
                    "llm.messages_count":   len(messages)}) as span:
        result = _orig_create(model=model, messages=messages,
                              temperature=temperature, max_tokens=max_tokens, **kwargs)
        dur   = (time.time() - t0) * 1000
        total = result.usage.total_tokens
        cost  = (result.usage.prompt_tokens / 1000 * 0.03 +
                 result.usage.completion_tokens / 1000 * 0.06)

        span.set_attribute("llm.prompt_tokens",      result.usage.prompt_tokens)
        span.set_attribute("llm.completion_tokens",  result.usage.completion_tokens)
        span.set_attribute("llm.total_tokens",       total)
        span.set_attribute("llm.completion_id",      result.id)
        span.set_attribute("llm.estimated_cost_usd", round(cost, 6))

        ai_requests.add(1,   attributes={"llm.model": model})
        ai_tokens.record(total, attributes={"llm.model": model})
        ai_latency.record(dur,  attributes={"llm.model": model})
        ai_cost_est.record(cost, attributes={"llm.model": model})

        logger.info("openai completion received",
                    extra={"llm.model": model, "llm.total_tokens": total,
                           "llm.completion_id": result.id, "llm.response_ms": round(dur, 2),
                           "llm.estimated_cost_usd": round(cost, 6)})
        return result

openai.ChatCompletion.create = _inst_create


def classify_ticket(ticket_id, subject, body, customer_tier):
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Classify support tickets by category and severity. Respond with JSON only."},
            {"role": "user",   "content": f"Ticket: {subject}\n\nBody: {body[:200]}\n\nCustomer tier: {customer_tier}"},
        ],
        temperature=0.1,
        max_tokens=100,
    )
    import json as _json
    try:
        classification = _json.loads(response.choices[0].message.content)
    except Exception:
        classification = {"category": "unknown", "severity": "medium"}

    logger.info("ticket classified",
                extra={"ticket.id": ticket_id, "ticket.category": classification.get("category"),
                       "ticket.severity": classification.get("severity"),
                       "ticket.customer_tier": customer_tier,
                       "llm.model": "gpt-4o-mini"})
    return classification


tickets = [
    ("TKT-001", "Billing error on invoice #4521", "I was charged twice this month...", "enterprise"),
    ("TKT-002", "API rate limits too low for our use case", "We are hitting the rate limit...", "pro"),
    ("TKT-003", "Cannot log into my account", "Getting 401 errors since yesterday...", "free"),
    ("TKT-004", "GDPR data export request", "Requesting all personal data under GDPR...", "enterprise"),
    ("TKT-005", "Feature: support for webhooks", "Would love webhook support for order events...", "pro"),
]

print(f"\n[{SVC}] Classifying support tickets via patched OpenAI SDK...")
for ticket_id, subject, body, tier in tickets:
    cls = classify_ticket(ticket_id, subject, body, tier)
    icon = "🚨" if cls.get("severity") == "critical" else "✅"
    print(f"  {icon} {ticket_id}  {tier:<12}  category={cls.get('category'):<18}  severity={cls.get('severity')}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
