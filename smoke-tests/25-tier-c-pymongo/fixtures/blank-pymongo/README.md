# Product Catalog Service — blank fixture

A Python service that manages a product catalog stored in MongoDB.

## What it does

- Finds all products in a given category
- Applies a seasonal discount (updates price in place)
- Inserts a new product listing for the category

## SDK used

**pymongo** — the official MongoDB driver for Python. Uses
`MongoClient` → database → collection → `insert_one`, `find`, `update_one`.

Since no MongoDB server is available, a mock client is used that simulates
the same interface using an in-process dict.

## No observability

This app has no OpenTelemetry instrumentation. Run:

```
Observe this project.
```

The agent should assign **Tier C** (monkey-patch) because pymongo has no
official OTel instrumentation library. It should wrap `insert_one`, `find`,
and `update_one` with `SpanKind.CLIENT` spans carrying `db.system=mongodb`,
`db.mongodb.collection`, and `db.operation` attributes.
