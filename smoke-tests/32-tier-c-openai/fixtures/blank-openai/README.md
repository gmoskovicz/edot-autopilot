# Support Ticket Classifier — blank fixture

A Python service that classifies support tickets using the OpenAI API.

## What it does

- Sends each ticket (subject + body + customer tier) to GPT-4o-mini via `ChatCompletion.create`
- Parses the JSON response to extract `category` and `severity`
- Categories: billing, technical, account, feature-request, compliance
- Severities: low, medium, high, critical

## SDK used

**openai** — the official OpenAI Python SDK. Uses
`openai.ChatCompletion.create(model, messages, temperature, max_tokens)`.

Since no OpenAI API key is available, a mock `ChatCompletion` class is used
that simulates realistic LLM latency (200–800ms) and returns randomised
classification JSON.

## No observability

This app has no OpenTelemetry instrumentation. Run:

```
Observe this project.
```

The agent should assign **Tier C** (monkey-patch) because there is no official
`opentelemetry-instrumentation-openai` library. It should wrap
`ChatCompletion.create` with `SpanKind.CLIENT` spans carrying `llm.model`,
`llm.provider=openai`, `llm.prompt_tokens`, `llm.completion_tokens`,
`llm.total_tokens`, and `llm.estimated_cost_usd` attributes.
