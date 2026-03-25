# Tier A — Python FastAPI (Native EDOT)

Tests EDOT's zero-config auto-instrumentation for Python FastAPI.

**What EDOT auto-instruments:**
- All HTTP routes (method, route, status code, duration)
- Outbound HTTP calls (httpx, requests, urllib3)
- SQLAlchemy queries (if added)
- Redis calls (if added)

**What this test adds (Phase 3):**
- Business attributes on the orders endpoint: `order.amount_usd`, `customer.tier`, `fraud.score`, `fraud.decision`

## Run

```bash
cp .env.example .env
docker compose up

# Send test traffic
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"customer_id":"CUST-001","item":"Enterprise License","amount":4200,"customer_tier":"enterprise"}'
```

## Verify in Elastic

Kibana → Observability → APM → Services → `edot-fastapi-tier-a`

Expected spans:
- `POST /orders` with `customer.tier`, `fraud.score`, `fraud.decision`
- `GET /orders/{order_id}`
