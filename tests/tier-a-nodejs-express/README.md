# Tier A — Node.js Express (Native EDOT)

Tests EDOT's zero-config auto-instrumentation for Node.js / Express.

**What EDOT auto-instruments:**
- All Express routes (method, route, status code, duration)
- Outbound HTTP/HTTPS calls
- pg, mysql2, redis, amqplib connections (if present)

**What this test adds (Phase 3):**
- Business attributes: `order.value_usd`, `customer.tier`, `fraud.score`, `fraud.decision`

## Run

```bash
cp ../.env.example .env
docker compose up

# Test checkout flow
curl -X POST http://localhost:3001/checkout \
  -H "Content-Type: application/json" \
  -d '{"customerId":"C001","orderValue":4200,"customerTier":"enterprise","items":["license"]}'
```

## Verify in Elastic

Kibana → Observability → APM → Services → `edot-nodejs-express-tier-a`
