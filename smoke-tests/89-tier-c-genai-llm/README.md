# Test 89 — Tier C: Gen-AI / LLM Observability

Instruments LLM API calls (OpenAI, Anthropic, AWS Bedrock) using the official
OpenTelemetry `gen_ai.*` semantic conventions.

**No real LLM API key needed** — uses mocked responses with correct span shapes.

## What it emits

| Signal | Details |
|---|---|
| Traces | `gen_ai.chat` spans with `gen_ai.system`, `gen_ai.request.model`, token usage |
| Metrics | `gen_ai.client.token.usage` histogram, `gen_ai.client.operation.duration` |
| Logs | Per-call summaries with token counts (no raw prompt/response content) |

## Key semconv attributes

| Attribute | Example |
|---|---|
| `gen_ai.system` | `openai` / `anthropic` / `aws.bedrock` |
| `gen_ai.operation.name` | `chat` / `text_completion` / `embeddings` |
| `gen_ai.request.model` | `gpt-4o` / `claude-sonnet-4-6` |
| `gen_ai.response.finish_reasons` | `["stop"]` |
| `gen_ai.usage.input_tokens` | `247` |
| `gen_ai.usage.output_tokens` | `183` |

## Privacy rule

Never log raw prompt or completion content. Use content hashes for
debugging correlation. This test demonstrates the correct pattern.

## ES|QL query

```
FROM traces-apm*
| WHERE service.name == "smoke-tier-c-genai-llm"
| KEEP @timestamp, labels.gen_ai_system, labels.gen_ai_request_model,
       labels.gen_ai_usage_input_tokens, labels.gen_ai_usage_output_tokens
| SORT @timestamp DESC | LIMIT 20
```
