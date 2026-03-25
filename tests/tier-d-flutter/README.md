# Tier D — Flutter

Flutter (Dart) has no official Elastic EDOT distribution or OpenTelemetry SDK as of 2025. Elastic's SDKs cover Python, Node.js, Java, .NET, PHP, Ruby, and Go — not Dart/Flutter.

**Strategy:** `OtelSidecar` — a 60-line Dart class that POSTs JSON to the sidecar. The sidecar runs alongside your backend (or on-device for debugging) and forwards OTLP spans to Elastic.

## Architecture

```
Flutter App → HTTP POST → otel-sidecar → OTLP → Elastic APM
```

In production, the sidecar runs as a sidecar container alongside your API backend. The Flutter app posts to `https://your-api.example.com/otel` (proxied to the sidecar).

## What gets instrumented

```dart
// Start a checkout span
final span = await _otel.startSpan('checkout.initiated', attributes: {
  'customer.tier': 'enterprise',
  'cart.value_usd': 4200.00,
  'platform': 'flutter',
});

// End with result
await span.end(attributes: {
  'checkout.status': 'success',
  'order.id': 'ORD-001',
  'fraud.decision': 'approved',
});
```

Elastic APM shows:
- Checkout completion rates by customer tier
- Fraud block rates
- Order values
- Platform-specific issues (iOS vs Android)

## Run

```bash
# 1. Start sidecar
cd ../../otel-sidecar
OTEL_SERVICE_NAME=flutter-tier-d docker compose up -d

# 2. Run Flutter app (with sidecar URL)
flutter run --dart-define=OTEL_SIDECAR_URL=http://localhost:9411
```

## Production setup

In production, expose the sidecar behind your API gateway:
- `POST /api/otel` → proxied to sidecar on the backend
- No direct mobile-to-sidecar connection (firewall/auth)
- Sidecar shares the network namespace with your API container

## Verify in Elastic

Kibana → Observability → APM → Services → `flutter-tier-d`
