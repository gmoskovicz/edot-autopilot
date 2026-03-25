# Phase 3: Business Span Enrichment

This is the differentiator that makes this approach valuable for engineering leadership and product teams — not just the ops team.

## The problem with generic auto-instrumentation

Every observability tool auto-instruments the HTTP layer. You get:
```
span: POST /api/checkout  http.status_code=500  duration=340ms
```

This tells you:
- Something failed
- It was slow
- Nothing else

## What business enrichment adds

After reading the checkout handler and extracting what has business meaning:
```
span: checkout.complete
  order.id = ORD-2847
  order.value_usd = 4200.00
  order.item_count = 3
  customer.tier = enterprise
  customer.age_days = 2
  payment.method = wire_transfer
  fraud.score = 0.87
  fraud.decision = blocked
  inventory.all_reserved = false
```

Now you can answer:
- "Was this a paying customer?" → `customer.tier = enterprise`
- "Why did it fail?" → `fraud.decision = blocked`
- "How much revenue was lost?" → `order.value_usd = 4200.00`
- "Is this a pattern?" → filter by `fraud.score > 0.85` across all time

## The 2am test

For every Golden Path span, ask: *"If this span appeared in an alert at 2am, would the on-call engineer know exactly what happened and what to do?"*

If yes: the enrichment is sufficient.
If no: what's missing that would change their first action?

## Standard enrichment by flow type

### Revenue-bearing flows
```python
span.set_attribute("order.value_usd",    order.total / 100)
span.set_attribute("order.currency",     order.currency)
span.set_attribute("payment.method",     payment.method)
span.set_attribute("subscription.plan",  customer.plan)
```

### Customer-facing flows (no PII)
```python
span.set_attribute("customer.tier",      customer.tier)       # free/pro/enterprise
span.set_attribute("customer.segment",   customer.segment)    # smb/mid-market/enterprise
span.set_attribute("account.age_days",   customer.days_since_signup)
span.set_attribute("account.region",     customer.region)     # us/eu/apac
```

### Failure paths
```python
span.set_attribute("error.category",     "upstream")          # auth/quota/upstream/data
span.set_attribute("retry.attempt",      attempt_number)
span.set_attribute("circuit_breaker.state", cb.state)         # open/closed/half-open
```

### Async / queue flows
```python
span.set_attribute("queue.name",         queue_name)
span.set_attribute("queue.depth",        queue.depth())
span.set_attribute("consumer.lag_ms",    lag)
span.set_attribute("message.age_ms",     msg_age)
```

### External dependency calls
```python
span.set_attribute("dependency.name",        "payment-gateway")
span.set_attribute("dependency.sla_ms",      300)             # contract SLA
span.set_attribute("dependency.actual_ms",   actual_duration)
span.set_attribute("dependency.sla_breached", actual > 300)
```

## What NOT to add

- **No PII**: email, name, phone, credit card, SSN. Use `customer.tier` not `customer.email`.
- **No secrets**: API keys, tokens, passwords — never in spans.
- **No noise**: every field should answer a question someone would ask during an incident.

## ES|QL queries that become possible after enrichment

```sql
-- Revenue lost to fraud blocks today
FROM traces-apm*
| WHERE span.name == "checkout.complete"
  AND labels.fraud_decision == "blocked"
  AND @timestamp > now() - 1d
| STATS total_blocked_revenue = SUM(labels.order_value_usd)

-- P99 checkout time by customer tier
FROM traces-apm*
| WHERE transaction.name == "POST /checkout"
| STATS p99 = PERCENTILE(transaction.duration.us, 99) BY labels.customer_tier

-- Enterprise customers hitting rate limits
FROM traces-apm*
| WHERE labels.error_category == "quota"
  AND labels.customer_tier == "enterprise"
| STATS count = COUNT() BY service.name, labels.customer_segment
| SORT count DESC
```

These queries are impossible without the enrichment attributes.
