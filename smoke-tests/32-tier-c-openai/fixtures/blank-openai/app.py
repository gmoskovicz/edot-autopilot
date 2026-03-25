"""
Support Ticket Classifier — OpenAI Python SDK

No observability. Run `Observe this project.` to add it.
"""

import uuid
import time
import random
import json


# ── Mock OpenAI SDK (simulates real openai without an API key) ─────────────────
CATEGORIES = ["billing", "technical", "account", "feature-request", "compliance"]
SEVERITIES = ["low", "medium", "high", "critical"]


class _MockChoice:
    def __init__(self, content):
        self.message = type("Msg", (), {"content": content, "role": "assistant"})()


class _MockCompletion:
    def __init__(self, model, prompt_tokens, completion_tokens, content):
        self.id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        self.model = model
        self.choices = [_MockChoice(content)]
        self.usage = type("Usage", (), {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        })()


class _MockChatCompletion:
    @staticmethod
    def create(model, messages, temperature=0.7, max_tokens=150, **kwargs):
        time.sleep(random.uniform(0.2, 0.8))  # realistic LLM latency
        prompt_tokens = int(sum(len(m["content"].split()) * 1.3 for m in messages))
        completion_tokens = random.randint(20, 80)
        category = random.choice(CATEGORIES)
        severity = random.choice(SEVERITIES)
        content = json.dumps({
            "category": category,
            "severity": severity,
            "confidence": round(random.uniform(0.75, 0.99), 2),
        })
        return _MockCompletion(model, prompt_tokens, completion_tokens, content)


class openai:
    ChatCompletion = _MockChatCompletion
    api_key = "sk-fake-key-for-smoke-test"


# ── Application code ───────────────────────────────────────────────────────────

def classify_ticket(ticket_id, subject, body, customer_tier):
    """Classify a support ticket using GPT and return category + severity."""
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "Classify support tickets by category and severity. Respond with JSON only.",
            },
            {
                "role": "user",
                "content": f"Ticket: {subject}\n\nBody: {body[:200]}\n\nCustomer tier: {customer_tier}",
            },
        ],
        temperature=0.1,
        max_tokens=100,
    )

    try:
        classification = json.loads(response.choices[0].message.content)
    except Exception:
        classification = {"category": "unknown", "severity": "medium"}

    print(f"  {ticket_id}: {classification.get('category')} / {classification.get('severity')}")
    return classification


if __name__ == "__main__":
    tickets = [
        ("TKT-001", "Billing error on invoice #4521", "I was charged twice this month...", "enterprise"),
        ("TKT-002", "API rate limits too low for our use case", "We are hitting the rate limit...", "pro"),
        ("TKT-003", "Cannot log into my account", "Getting 401 errors since yesterday...", "free"),
        ("TKT-004", "GDPR data export request", "Requesting all personal data under GDPR...", "enterprise"),
        ("TKT-005", "Feature: support for webhooks", "Would love webhook support for order events...", "pro"),
    ]

    for ticket_id, subject, body, tier in tickets:
        classify_ticket(ticket_id, subject, body, tier)

    print("All tickets classified")
