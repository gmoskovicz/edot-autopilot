#!/usr/bin/env python3
"""
Smoke test: Tier D — Lua / game server scripting (sidecar simulation).

Simulates a Lua game server script submitting observability via the HTTP sidecar.
Business scenario: multiplayer game session management — player matchmaking,
in-game economy transactions, achievement unlock events.

Run:
    cd smoke-tests && python3 41-tier-d-lua/smoke.py
"""

import os, sys, time, random, uuid
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind

SVC = "smoke-tier-d-lua"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

matches_created    = meter.create_counter("lua.matches_created")
transactions       = meter.create_counter("lua.economy_transactions")
achievements_fired = meter.create_counter("lua.achievements_unlocked")
matchmake_ms       = meter.create_histogram("lua.matchmake_duration_ms", unit="ms")
economy_coins      = meter.create_histogram("lua.transaction_coins")

GAME_EVENTS = [
    {"type": "match_create",  "player_ids": ["P-7711", "P-3344", "P-9922", "P-1156"], "map": "Crossroads",  "mode": "ranked"},
    {"type": "purchase",      "player_id": "P-7711", "item": "legendary_sword",        "coins": 2500,        "currency": "gold"},
    {"type": "achievement",   "player_id": "P-3344", "achievement": "first_blood",     "xp_reward": 500,     "rare": False},
    {"type": "match_create",  "player_ids": ["P-5544", "P-8823"],                      "map": "Desert_Dune", "mode": "casual"},
    {"type": "purchase",      "player_id": "P-9922", "item": "battle_pass",            "coins": 0,           "currency": "premium", "usd": 9.99},
    {"type": "achievement",   "player_id": "P-9922", "achievement": "sharpshooter",    "xp_reward": 1500,    "rare": True},
]

def process_game_event(event):
    t0 = time.time()

    if event["type"] == "match_create":
        session_id = f"MATCH-{uuid.uuid4().hex[:8].upper()}"
        with tracer.start_as_current_span("lua.matchmaker.create_session", kind=SpanKind.INTERNAL,
                attributes={"game.event_type": "match_create", "game.map": event["map"],
                            "game.mode": event["mode"], "game.player_count": len(event["player_ids"]),
                            "game.session_id": session_id}) as span:
            with tracer.start_as_current_span("lua.matchmaker.verify_players", kind=SpanKind.CLIENT,
                    attributes={"db.operation": "HGET", "db.system": "redis"}):
                time.sleep(random.uniform(0.005, 0.015))
            with tracer.start_as_current_span("lua.matchmaker.allocate_server", kind=SpanKind.CLIENT,
                    attributes={"game.region": "us-east-1"}):
                time.sleep(random.uniform(0.02, 0.06))
            dur = (time.time() - t0) * 1000
            matches_created.add(1, attributes={"game.mode": event["mode"], "game.map": event["map"]})
            matchmake_ms.record(dur, attributes={"game.mode": event["mode"]})
            logger.info("match created", extra={"game.session_id": session_id, "game.map": event["map"],
                                                 "game.mode": event["mode"],
                                                 "game.player_count": len(event["player_ids"])})
        return session_id

    elif event["type"] == "purchase":
        tx_id = f"TX-{uuid.uuid4().hex[:10].upper()}"
        with tracer.start_as_current_span("lua.economy.process_purchase", kind=SpanKind.INTERNAL,
                attributes={"game.event_type": "purchase", "game.player_id": event["player_id"],
                            "economy.item": event["item"], "economy.currency": event["currency"],
                            "economy.coins": event["coins"]}) as span:
            time.sleep(random.uniform(0.01, 0.04))
            span.set_attribute("economy.tx_id", tx_id)
            transactions.add(1, attributes={"economy.currency": event["currency"], "economy.item": event["item"]})
            if event["coins"] > 0:
                economy_coins.record(event["coins"], attributes={"economy.currency": event["currency"]})
            logger.info("purchase processed", extra={"game.player_id": event["player_id"],
                                                      "economy.item": event["item"],
                                                      "economy.tx_id": tx_id, "economy.coins": event["coins"]})
        return tx_id

    elif event["type"] == "achievement":
        with tracer.start_as_current_span("lua.achievements.unlock", kind=SpanKind.INTERNAL,
                attributes={"game.event_type": "achievement", "game.player_id": event["player_id"],
                            "achievement.name": event["achievement"], "achievement.xp_reward": event["xp_reward"],
                            "achievement.rare": event["rare"]}) as span:
            time.sleep(random.uniform(0.005, 0.02))
            achievements_fired.add(1, attributes={"achievement.name": event["achievement"],
                                                   "achievement.rare": str(event["rare"])})
            logger.info("achievement unlocked", extra={"game.player_id": event["player_id"],
                                                        "achievement.name": event["achievement"],
                                                        "achievement.xp_reward": event["xp_reward"],
                                                        "achievement.rare": event["rare"]})

print(f"\n[{SVC}] Simulating Lua game server event processing...")
for event in GAME_EVENTS:
    result = process_game_event(event)
    if event["type"] == "match_create":
        print(f"  ✅ MATCH  map={event['map']:<15}  mode={event['mode']:<8}  players={len(event['player_ids'])}  id={result}")
    elif event["type"] == "purchase":
        coins = f"{event['coins']} {event['currency']}" if event["coins"] else f"${event.get('usd', 0):.2f} USD"
        print(f"  ✅ PURCHASE  player={event['player_id']}  item={event['item']:<20}  cost={coins}")
    else:
        icon = "🏆" if event["rare"] else "✅"
        print(f"  {icon} ACHIEVEMENT  player={event['player_id']}  {event['achievement']:<20}  xp=+{event['xp_reward']}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
