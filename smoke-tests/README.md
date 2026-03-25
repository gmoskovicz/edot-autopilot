# Smoke Tests — EDOT Autopilot

Minimal, runnable tests that prove each tier works end-to-end with the Elastic cluster.
All six tests were run and confirmed ✅ against the preciouy Observability deployment.

## What each test sends to Elastic APM

| Test | Service name | What it sends |
|------|-------------|---------------|
| `01-tier-a-python` | `smoke-tier-a-python` | 3 checkout spans (enterprise/free/pro) with fraud scores, nested payment spans |
| `02-tier-a-nodejs` | `smoke-tier-a-nodejs` | Same checkout scenario, Node.js OTel SDK |
| `03-tier-b-manual-wrap` | `smoke-tier-b-manual-wrap` | Manually wrapped handler spans (Python 2.7 pattern) |
| `04-tier-c-monkey-patch` | `smoke-tier-c-monkey-patch` | Monkey-patched Stripe mock spans |
| `05-tier-d-sidecar` (bash) | `smoke-tier-d-sidecar` | ETL batch spans, backup spans via curl |
| `05-tier-d-sidecar` (perl) | `smoke-tier-d-sidecar` | Invoice processing spans via LWP |
| `05-tier-d-sidecar` (python client) | `smoke-tier-d-sidecar-client` | All three sidecar patterns (event/start-end/error) |

## Quick start

```bash
cd smoke-tests

# 1. Set credentials
cp .env.example .env
# .env is pre-filled for the preciouy cluster

# 2. Install Python dependencies (once)
pip3 install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http

# 3. Run everything
bash run-all.sh
```

## Run individual tests

```bash
cd smoke-tests

# Tier A — Python
python3 01-tier-a-python/smoke.py

# Tier A — Node.js
cd 02-tier-a-nodejs && npm install && node smoke.js

# Tier B — Manual wrapping
python3 03-tier-b-manual-wrap/smoke.py

# Tier C — Monkey-patch
python3 04-tier-c-monkey-patch/smoke.py

# Tier D — Sidecar (start sidecar first)
source 05-tier-d-sidecar/start-sidecar.sh
bash 05-tier-d-sidecar/smoke-bash.sh
perl 05-tier-d-sidecar/smoke-perl.pl     # needs: cpan install LWP::UserAgent JSON
python3 05-tier-d-sidecar/smoke-python.py

# Verify all confirmed in Elastic
python3 06-verify/check_spans.py
```

## Run with Docker (no local dependencies needed)

```bash
cd smoke-tests
docker compose up
```

Runs all tiers in isolated containers, including the sidecar for Tier D tests.

## Verify in Kibana

After running, open Kibana → Observability → APM → Services.
Filter by service name: `smoke-*`

Or run the ES|QL query in Kibana Discover:
```sql
FROM traces-apm*
| WHERE service.name LIKE "smoke*"
| KEEP @timestamp, service.name, transaction.name,
       labels.order_value_usd, labels.customer_tier, labels.fraud_decision
| SORT @timestamp DESC
| LIMIT 20
```

## Enable ES content verification

By default, verification only pings the OTLP endpoint (HTTP 200 = accepted).
To also query span content from Elasticsearch, create a read API key:

1. Kibana → Stack Management → Security → API Keys → Create API Key
2. Set: `index` privilege on `traces-apm*`, operation `read`
3. Add to `.env`:
   ```
   ELASTIC_ES_READ_API_KEY=<your-key>
   ```

## Prerequisites per test

| Test | Requirement |
|------|------------|
| Python tests | `pip3 install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http` |
| Node.js test | Node.js 18+ — `npm install` in `02-tier-a-nodejs/` |
| Perl test | `cpan install LWP::UserAgent JSON` |
| Tier D tests | Python 3 + OTel SDK (for the sidecar process) |
| Docker tests | Docker + Docker Compose |
