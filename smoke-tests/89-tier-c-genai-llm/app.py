"""
Smoke test 89 — Tier C: Gen-AI / LLM observability
Instruments LLM API calls (OpenAI, Anthropic, Bedrock) with gen_ai.* semconv.
No real LLM API key needed — uses mocked responses.

Emits:
  Traces: gen_ai.client.operation spans with token usage, model, finish reason
  Metrics: gen_ai.client.token.usage histogram, gen_ai.client.operation.duration
  Logs:   per-request prompt/response summaries (no PII — content hashes only)
"""
import sys, os, time, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from o11y_bootstrap import setup_o11y

from opentelemetry import trace, metrics
from opentelemetry.trace import SpanKind

SERVICE_NAME = "smoke-tier-c-genai-llm"
tracer, logger, meter = setup_o11y(SERVICE_NAME)

# --- Metrics (gen_ai.* semconv) ---
token_usage = meter.create_histogram(
    "gen_ai.client.token.usage",
    unit="{token}",
    description="Number of tokens used in LLM API call",
)
operation_duration = meter.create_histogram(
    "gen_ai.client.operation.duration",
    unit="s",
    description="Duration of LLM API operation",
)

# --- Mock LLM providers ---
PROVIDERS = [
    {"name": "openai",    "model": "gpt-4o",             "system": "openai"},
    {"name": "anthropic", "model": "claude-sonnet-4-6",   "system": "anthropic"},
    {"name": "bedrock",   "model": "amazon.nova-pro",     "system": "aws.bedrock"},
]


def mock_llm_call(provider: dict, prompt: str) -> dict:
    """Simulate an LLM API call — no real API key needed."""
    time.sleep(random.uniform(0.05, 0.3))
    input_tokens  = random.randint(50, 500)
    output_tokens = random.randint(20, 300)
    return {
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
        "finish_reason": random.choice(["stop", "stop", "stop", "length"]),
        "response_hash": hash(prompt) & 0xFFFFFFFF,  # never log raw content
    }


def instrumented_llm_call(provider: dict, prompt: str, operation: str = "chat"):
    start = time.time()

    with tracer.start_as_current_span(
        f"gen_ai.{operation}",                        # OTel gen_ai semconv span name
        kind=SpanKind.CLIENT,
        attributes={
            # Required gen_ai.* attributes
            "gen_ai.system":              provider["system"],
            "gen_ai.operation.name":      operation,
            "gen_ai.request.model":       provider["model"],
            # Optional request attributes
            "gen_ai.request.max_tokens":  512,
            "gen_ai.request.temperature": 0.7,
            # Business context (not in semconv — project-specific)
            "app.feature":                "customer-support-bot",
            "app.request.intent":         "refund_inquiry",
        }
    ) as span:
        try:
            result = mock_llm_call(provider, prompt)

            # Response attributes (set after call)
            span.set_attribute("gen_ai.response.model",          provider["model"])
            span.set_attribute("gen_ai.response.finish_reasons", [result["finish_reason"]])
            span.set_attribute("gen_ai.usage.input_tokens",      result["input_tokens"])
            span.set_attribute("gen_ai.usage.output_tokens",     result["output_tokens"])

            # Span event for prompt/completion (hash only — never log raw content)
            span.add_event("gen_ai.content.prompt",
                {"gen_ai.prompt": f"[hash:{hash(prompt) & 0xFFFF}]"})
            span.add_event("gen_ai.content.completion",
                {"gen_ai.completion": f"[hash:{result['response_hash']}]"})

            duration = time.time() - start

            # Metrics
            attrs = {
                "gen_ai.system":         provider["system"],
                "gen_ai.operation.name": operation,
                "gen_ai.request.model":  provider["model"],
            }
            token_usage.record(result["input_tokens"],  {**attrs, "gen_ai.token.type": "input"})
            token_usage.record(result["output_tokens"], {**attrs, "gen_ai.token.type": "output"})
            operation_duration.record(duration, attrs)

            logger.info("LLM call complete", extra={"attributes": {
                "gen_ai.system":                 provider["system"],
                "gen_ai.request.model":          provider["model"],
                "gen_ai.usage.input_tokens":     result["input_tokens"],
                "gen_ai.usage.output_tokens":    result["output_tokens"],
                "gen_ai.response.finish_reason": result["finish_reason"],
                "duration_ms":                   round(duration * 1000),
            }})

            return result

        except Exception as e:
            span.record_exception(e, attributes={"exception.escaped": True})
            span.set_status(trace.StatusCode.ERROR, str(e))
            raise


def run():
    print(f"Smoke test: {SERVICE_NAME}")
    print("Instrumented LLM providers: OpenAI, Anthropic, AWS Bedrock\n")

    prompts = [
        "I need a refund for order #12345",
        "What is the status of my shipment?",
        "How do I cancel my subscription?",
    ]

    for provider, prompt in zip(PROVIDERS * 2, prompts * 2):
        result = instrumented_llm_call(provider, prompt)
        print(f"  [{provider['name']:10}] {provider['model']:30} "
              f"in={result['input_tokens']:3} out={result['output_tokens']:3} "
              f"finish={result['finish_reason']}")

    print(f"\n✓ {SERVICE_NAME} — {len(PROVIDERS * 2)} LLM calls emitted → Elastic")


if __name__ == "__main__":
    run()
