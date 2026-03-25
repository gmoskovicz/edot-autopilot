# blank-lua — Multiplayer Game Server Event Handler (Lua)

## What this script does

`game_server.lua` is a LuaJIT script embedded in a multiplayer game server
(C++ engine + Lua scripting). It handles three types of game events read from
stdin as JSON lines:

1. **matchmaker.create_session** — verifies player online status via Redis
   (`HGET player:<id> status`), allocates a game server IP/port, persists the
   session record in Redis with a 2-hour TTL, and logs match creation
2. **economy.process_purchase** — deducts coins from the player's balance in
   Redis, grants the item to the player's inventory set, records the
   transaction with 30-day audit retention, and logs the purchase
3. **achievements.unlock** — checks whether the achievement is already
   unlocked (`SISMEMBER`), grants it and awards XP if not, and logs the
   unlock event

The script reads JSON events from stdin (one per line), processes them
sequentially, and prints a summary on exit.

## Why it has no observability

This is a **Tier D** legacy application. Lua / LuaJIT embedded in a game
engine has no OpenTelemetry SDK. The Lua VM cannot load native OTel agents.

There are no HTTP calls, no sidecar references, no trace/span IDs — just
`print()` statements and Redis operations.

The EDOT Autopilot agent must:
1. Copy `otel-sidecar.py` into the project
2. Modify `game_server.lua` to add `socket.http` or `lua-requests` HTTP POST
   calls targeting the sidecar so that each event handler emits a span
3. Create `.otel/slos.json` and `.otel/golden-paths.md`
