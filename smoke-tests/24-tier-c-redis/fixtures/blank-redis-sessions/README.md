# Auth Session Service

A Python service that manages user sessions using Redis as a cache. Used by
the authentication service to store and retrieve session tokens.

## Key flows

- `login(user_id, user_data)` — Checks Redis for an existing session (`GET`).
  On cache hit, returns the existing session. On miss, creates a new session
  and stores it (`SET` with TTL).
- `logout(user_id)` — Deletes the session key from Redis (`DEL`).
- `get_session(user_id)` — Read-only lookup (`GET`) without creating a session.
- `refresh_session(user_id)` — Extends session TTL (`EXPIRE`).

## Business context

Sessions are stored in Redis DB 1 under keys `session:{user_id}`. TTL is
3600 seconds (1 hour) by default, configurable via `SESSION_TTL_SEC`.

Redis host/port come from `REDIS_HOST` / `REDIS_PORT` env vars (default:
`redis.internal:6379`).

User tiers: `free`, `pro`, `enterprise`. Enterprise users have priority
session handling in the auth flow.

## Stack

- redis-py — Official Redis Python client (no built-in OTel support)

## No observability yet

This service has zero OpenTelemetry instrumentation. redis-py has no built-in
OTel support.

The agent should apply Tier C (monkey-patching): patch the `Redis.get`,
`Redis.set`, and `Redis.delete` methods on the `redis.Redis` class with
instrumented wrappers.

Expected instrumentation:
- `redis.get` (CLIENT span) — `db.system=redis`, `db.operation=GET`,
  `redis.key`, `redis.hit` (bool), `net.peer.name`
- `redis.set` (CLIENT span) — `db.system=redis`, `db.operation=SET`,
  `redis.key`, `redis.ttl_sec`
- `redis.delete` (CLIENT span) — `db.system=redis`, `db.operation=DEL`,
  `redis.keys_count`
- Metrics: `redis.commands` counter, `redis.cache_hits` / `redis.cache_misses`
  counters, `redis.command_ms` histogram
- Error paths: `record_exception` + `set_status(ERROR)` on connection errors
