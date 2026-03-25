# Business Span Enrichment — Complete Guide

> How to turn generic auto-instrumentation output into spans that answer real questions at 2am — with concrete before/after examples and a framework for identifying what to capture.

## What business span enrichment is and why it matters

Auto-instrumentation is a starting point, not a destination.

When you add the EDOT Python agent to a FastAPI application, you immediately get spans for every HTTP request: method, path, status code, duration. When you add the EDOT Java agent to a Spring Boot service, you get spans for every JDBC query: SQL statement, table name, duration. This is valuable — it gives you latency percentiles, error rates, and dependency maps.

But none of it answers the questions that actually matter during an incident:

- Was this a paying customer or a free trial user?
- What was the order value that failed?
- Was this a first-time authorization or a retry?
- Is the fraud score elevated?
- Which warehouse is currently unable to fulfill?
- Did the SLA breach affect enterprise customers or standard tier?

Auto-instrumentation instruments what it can detect: HTTP calls, DB queries, framework hooks. It does not read your code. It does not know that `POST /api/v1/txn` is a payment authorization. It does not know that `fraud_score` is the single most important field an on-call engineer needs during a chargebacks incident.

Business span enrichment is the practice of reading your code, identifying the data that has business meaning, and attaching it to spans as attributes. The result is that every span carries enough context for the on-call engineer to understand what happened without opening a database or a Slack thread.

## The before / after for a checkout flow

This is the most concrete way to illustrate the difference.

**Before — generic auto-instrumentation output:**

```
POST /api/checkout
  http.method:      POST
  http.route:       /api/checkout
  http.status_code: 200
  duration:         340ms
```

This span tells you: a POST to `/api/checkout` succeeded in 340ms. That is all. You have no idea what order it was, whether it was a high-value customer, whether fraud checks passed, whether inventory was actually reserved, or what payment method was used.

**After — business-enriched span:**

```
checkout.complete
  order.id:                order_9a3f1c
  order.value_usd:         847.50
  order.item_count:        3
  customer.tier:           enterprise
  customer.age_days:       412
  payment.method:          card
  fraud.score:             0.12
  fraud.decision:          allow
  inventory.all_reserved:  true
  duration:                340ms
```

This span tells you: an enterprise customer placed an $847.50 order with 3 items, paid by card, fraud score was low, all inventory was reserved, and it completed in 340ms. If this span appears in a P1 alert at 2am, the on-call engineer knows exactly what happened.

**The test**: *If this span appeared in an alert at 2am, would the on-call engineer know exactly what happened and what to do next?*

If the answer is no, the span needs more enrichment.

## The 5 categories of business attributes

### 1. Revenue-bearing attributes

For any flow that involves money, the span must carry the value.

| Attribute | When to use |
|---|---|
| `order.value_usd` | E-commerce order submission |
| `subscription.mrr` | Subscription creation or renewal |
| `invoice.amount` | Invoice generation or payment |
| `payment.method` | Any payment event |
| `refund.amount` | Refund processing |
| `transaction.value` | Any financial transaction |

These attributes let you answer: "How much revenue was affected by this incident?" and "Are the failures concentrated in high-value transactions?"

### 2. Customer identity attributes (no PII)

Do not put names, email addresses, or full card numbers in spans. Do put the attributes that let you understand who is affected without identifying individuals.

| Attribute | When to use |
|---|---|
| `customer.tier` | `free`, `pro`, `enterprise`, `trial` |
| `customer.segment` | `smb`, `mid-market`, `enterprise` |
| `account.age_days` | Days since account creation |
| `customer.region` | Geographic region (not precise location) |
| `session.authenticated` | boolean |

These attributes answer: "Are failures concentrated in a specific tier?" and "Are new users disproportionately affected?"

### 3. Failure actionability attributes

When a span represents an error, it must carry enough context for the engineer to act — not just know that something failed.

| Attribute | When to use |
|---|---|
| `error.category` | `auth`, `quota`, `upstream`, `data`, `timeout` |
| `retry.attempt` | Which retry this is (0 = first attempt) |
| `circuit_breaker.state` | `closed`, `open`, `half-open` |
| `dependency.name` | Which downstream system failed |
| `quota.limit` | The limit that was breached |
| `quota.current` | The current usage when the error occurred |

These attributes answer: "Is this a code bug, a quota issue, an upstream outage, or bad data?" The answer determines which team to page.

### 4. Async / queue flow attributes

Spans in queue consumers and background jobs need lag information. Without it, a span duration of 5ms tells you nothing about whether messages are being processed in time.

| Attribute | When to use |
|---|---|
| `queue.depth` | Number of messages waiting when processing started |
| `consumer.lag_ms` | How long the message waited in the queue |
| `message.age_ms` | Time since the message was originally produced |
| `batch.size` | Number of records in a batch job run |
| `batch.failed_count` | How many records in the batch failed |

These attributes answer: "Is the queue backing up?" and "Are messages processing within their expected SLA window?"

### 5. Dependency SLA attributes

When your service calls an external dependency (payment gateway, fraud API, email provider, internal microservice), the span should carry whether the call met its SLA.

| Attribute | When to use |
|---|---|
| `dependency.sla_ms` | The expected maximum latency (from code comments, contracts, or timeouts) |
| `dependency.actual_ms` | The actual latency |
| `dependency.sla_breached` | boolean — true if actual > sla |
| `dependency.provider` | `stripe`, `sendgrid`, `internal-auth-service` |
| `dependency.region` | Which region/endpoint was called |

These attributes enable SLA breach alerting directly from spans, without a separate monitoring system.

## How to identify what attributes matter: reading the code

This is the skill that separates useful instrumentation from noise. Do not guess what to capture. Read the code.

**Step 1: Find the entry point handler.**

For a checkout flow, find the controller or route handler that processes the request. Read it fully.

**Step 2: Identify what data the handler receives and reads.**

What fields come in on the request? What is loaded from the database? What is computed? Every piece of data the handler reads is a candidate.

**Step 3: Apply the 2am test to each candidate.**

For each piece of data, ask: "If I'm paged at 2am with a checkout failure, would knowing this help me understand what happened or what to do?"

- `order.value_usd` — yes, I need to know severity
- `customer.tier` — yes, enterprise SLA is different
- `fraud.score` — yes, elevated score changes the investigation
- `inventory.item_sku[0]` — probably no, too granular
- `http.request.header.x-forwarded-for` — no, IP addresses are noise

**Step 4: Capture the outcome, not just the input.**

An incoming `order.value_usd` is useful. The outgoing `inventory.all_reserved` (a boolean computed during the handler) is equally useful — it tells you whether the happy path completed.

**Step 5: Name spans after business actions, not technical operations.**

| Instead of... | Use... |
|---|---|
| `POST /api/v1/checkout` | `checkout.complete` |
| `execute_query` | `order.persist` |
| `send_message` | `fulfillment.notify` |
| `call_external_api` | `fraud.evaluate` |

## Full code example: checkout flow enrichment

```python
# Before enrichment — what auto-instrumentation gives you
# span: POST /api/checkout  http.status_code=200  duration=340ms

# After enrichment — what business context looks like
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def checkout(request: CheckoutRequest, customer: Customer):
    order = build_order(request, customer)

    with tracer.start_as_current_span("checkout.complete") as span:
        # Revenue context
        span.set_attribute("order.id",            order.id)
        span.set_attribute("order.value_usd",     order.total_cents / 100)
        span.set_attribute("order.item_count",    len(order.items))

        # Customer context (no PII)
        span.set_attribute("customer.tier",       customer.tier)
        span.set_attribute("customer.age_days",   customer.days_since_signup)
        span.set_attribute("customer.segment",    customer.segment)

        # Payment context
        span.set_attribute("payment.method",      request.payment_method)

        try:
            # Fraud evaluation
            fraud_result = await fraud_service.evaluate(order, customer)
            span.set_attribute("fraud.score",     fraud_result.score)
            span.set_attribute("fraud.decision",  fraud_result.decision)

            if fraud_result.decision == "block":
                span.set_attribute("error.category", "fraud")
                span.set_status(trace.StatusCode.ERROR, "blocked by fraud engine")
                raise FraudBlockedException(order.id)

            # Inventory reservation
            inventory = await inventory_service.reserve(order.items)
            span.set_attribute("inventory.all_reserved", inventory.all_reserved)
            span.set_attribute("inventory.partial",      inventory.partial_count > 0)

            # Payment authorization — dependency SLA tracking
            auth_start = time.monotonic()
            payment = await payment_service.authorize(order, request.payment_token)
            auth_ms = int((time.monotonic() - auth_start) * 1000)

            span.set_attribute("payment.charge_id",         payment.charge_id)
            span.set_attribute("payment.status",            payment.status)
            span.set_attribute("dependency.sla_ms",         500)        # from gateway contract
            span.set_attribute("dependency.actual_ms",      auth_ms)
            span.set_attribute("dependency.sla_breached",   auth_ms > 500)

            # Persist
            saved_order = await order_repo.save(order)
            span.set_attribute("order.status",              "confirmed")

            return saved_order

        except FraudBlockedException:
            raise
        except PaymentDeclinedException as e:
            span.set_attribute("error.category",            "payment")
            span.set_attribute("payment.decline_code",      e.code)
            span.set_status(trace.StatusCode.ERROR, "payment declined")
            raise
        except InventoryException as e:
            span.set_attribute("error.category",            "inventory")
            span.set_attribute("inventory.failed_skus",     ",".join(e.failed_skus))
            span.set_status(trace.StatusCode.ERROR, "inventory reservation failed")
            raise
        except Exception as e:
            span.set_attribute("error.category",            "internal")
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            raise
```

## How business attributes flow into Elastic analytics

Every attribute you set on a span becomes a searchable field in Elastic. This unlocks several capabilities:

**ES|QL analytics**: Query your traces like a database. Find the p99 checkout duration for enterprise customers only. Identify which payment methods have the highest decline rate. Track fraud score distributions over time.

```esql
FROM traces-apm*
| WHERE service.name == "checkout-service"
  AND span.name == "checkout.complete"
  AND attributes.customer\.tier == "enterprise"
| STATS
    p99_ms     = PERCENTILE(span.duration.us / 1000, 99),
    error_rate = COUNT_IF(span.outcome == "failure") / COUNT(*) * 100
  BY bin(@timestamp, 1h)
| SORT @timestamp DESC
```

**ML anomaly detection**: Elastic's ML jobs can detect anomalies in business-specific metrics. An unusual spike in `fraud.score` values, or a drop in `inventory.all_reserved: true` rate, triggers an alert before users report problems.

**SLO definitions**: Define SLOs directly on business attributes. "99.9% of `checkout.complete` spans for `customer.tier: enterprise` must complete within 500ms" is a meaningful SLO that maps directly to a business commitment.

**Service Map enrichment**: The Kibana service map shows which services call which. With `dependency.sla_breached` on dependency spans, you can see at a glance which upstream services are regularly violating their SLA.

**Alerting**: Set up watchers or detection rules on business attributes. Alert when `fraud.decision: block` rate exceeds 2% in a rolling hour — that pattern may indicate a credential stuffing attack.

## Related

- [OpenTelemetry for Legacy Runtimes — making legacy code observable](./opentelemetry-legacy-runtimes.md)
- [Telemetry Sidecar Pattern — bridging runtimes that have no SDK](./telemetry-sidecar-pattern.md)
- [Elastic EDOT documentation](https://www.elastic.co/docs/reference/opentelemetry)
- [EDOT Autopilot on GitHub](https://github.com/gmoskovicz/edot-autopilot)

---

> Found this useful? [Star the repo](https://github.com/gmoskovicz/edot-autopilot) — it helps other developers build more meaningful observability.
