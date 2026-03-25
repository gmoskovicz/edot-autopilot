# Incident Alerting — blank fixture

A Python service that sends SLA breach alerts to Slack channels.

## What it does

- Posts a structured alert to `#ops-alerts` with incident details (service, SLA type, severity, breach duration)
- Sends a follow-up thread message to `#on-call` linking to the original alert
- Handles API errors (not_in_channel, rate limits) gracefully

## SDK used

**slack-sdk** — the official Slack SDK for Python. Uses
`WebClient(token=...).chat_postMessage(channel, text, blocks, thread_ts)`.

Since no Slack token is available, a mock `WebClient` simulates the API with
realistic latency (30–80ms) and a 2% random failure rate.

## No observability

This app has no OpenTelemetry instrumentation. Run:

```
Observe this project.
```

The agent should assign **Tier C** (monkey-patch) because there is no official
`opentelemetry-instrumentation-slack-sdk` library. It should wrap
`WebClient.chat_postMessage` with `SpanKind.CLIENT` spans carrying
`slack.channel`, `messaging.system=slack`, and `slack.message_ts` attributes,
and set `StatusCode.ERROR` on API failures.
