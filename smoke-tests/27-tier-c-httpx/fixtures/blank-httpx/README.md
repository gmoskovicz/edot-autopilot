# Currency Exchange Rate Fetcher — blank fixture

A Python service that fetches live FX rates and caches them via an HTTP API.

## What it does

- Makes GET requests to `api.fx-provider.io/v2/rates/{base}/{quote}`
- Caches each rate with a POST to `api.fx-provider.io/v2/cache/store`
- Supports five currency pairs: USD/EUR, USD/GBP, USD/JPY, EUR/USD, USD/BRL

## SDK used

**httpx** — a modern async-capable HTTP client for Python.
Uses `httpx.Client()` context manager with `.get()` and `.post()` methods.

Since no real FX API is available, a mock client simulates responses with
realistic latency (20–80ms) and a 5% random timeout failure rate.

## No observability

This app has no OpenTelemetry instrumentation. Run:

```
Observe this project.
```

The agent should assign **Tier C** (monkey-patch) because httpx has no
first-party OTel instrumentation. It should wrap `Client.get` and `Client.post`
with `SpanKind.CLIENT` spans carrying `http.method`, `http.url`, and
`http.status_code` attributes, and set `StatusCode.ERROR` on timeout failures.
