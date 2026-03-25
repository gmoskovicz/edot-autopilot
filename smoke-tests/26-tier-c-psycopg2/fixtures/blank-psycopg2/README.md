# Analytics Warehouse ETL — blank fixture

A Python ETL script that aggregates daily sales data into a PostgreSQL reporting schema.

## What it does

- Queries `orders` for a given date and region (`SELECT`)
- Computes total revenue and order count
- Inserts an aggregate row into `daily_sales_rollup` (`INSERT`)

## SDK used

**psycopg2** — the most popular PostgreSQL adapter for Python.
Uses `psycopg2.connect()` → `connection.cursor()` → `cursor.execute()` / `cursor.fetchall()`.

Since no PostgreSQL server is available, a mock is used that returns randomised
but structurally valid result sets.

## No observability

This app has no OpenTelemetry instrumentation. Run:

```
Observe this project.
```

The agent should assign **Tier C** (monkey-patch) because psycopg2 has no
official OTel instrumentation library. It should wrap `cursor.execute` with
`SpanKind.CLIENT` spans carrying `db.system.name=postgresql`,
`db.operation.name`, `db.query.text`, and `db.namespace` attributes.
