# Product Search Index — blank fixture

A Python service that syncs a product catalog to an Elasticsearch index.

## What it does

- Indexes product documents with `es.index(index, body, id)`
- Searches the index with `es.search(index, body)` to verify ingestion
- Updates each document's stock status with `es.update(index, id, body)`

## SDK used

**elasticsearch-py** — the official Elasticsearch Python client. Uses
`Elasticsearch(hosts=[...])` → `.index()`, `.search()`, `.update()`.

Since no Elasticsearch cluster is available, a mock client is used that
simulates the same interface using an in-process dict.

## No observability

This app has no OpenTelemetry instrumentation. Run:

```
Observe this project.
```

The agent should assign **Tier C** (monkey-patch) because the official
elasticsearch-py OTel instrumentation does not exist as a standalone package.
It should wrap `index`, `search`, and `update` with `SpanKind.CLIENT` spans
carrying `db.system=elasticsearch`, `elasticsearch.index`, and `db.operation`
attributes.
