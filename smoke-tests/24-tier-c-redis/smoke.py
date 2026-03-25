#!/usr/bin/env python3
"""
Smoke test: Tier C — redis-py client (monkey-patched).

Patches redis.Redis.get / set / delete / pipeline.
Business scenario: Session cache for a high-traffic auth service.

Run:
    cd smoke-tests && python3 24-tier-c-redis/smoke.py
"""

import os, sys, uuid, time, json
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-c-redis"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

redis_ops    = meter.create_counter("redis.commands")
redis_hits   = meter.create_counter("redis.cache_hits")
redis_misses = meter.create_counter("redis.cache_misses")
redis_latency= meter.create_histogram("redis.command_ms", unit="ms")

_cache = {}  # in-memory mock


class _MockRedis:
    def __init__(self, host="localhost", port=6379, db=0, decode_responses=True, **kwargs):
        self.host = host
        self.port = port
        self.db   = db

    def get(self, name):
        time.sleep(0.002)
        return _cache.get(name)

    def set(self, name, value, ex=None):
        time.sleep(0.002)
        _cache[name] = value
        return True

    def delete(self, *names):
        time.sleep(0.002)
        for n in names:
            _cache.pop(n, None)
        return len(names)

    def exists(self, *names):
        return sum(1 for n in names if n in _cache)

class redis:
    Redis = _MockRedis


_orig_get = _MockRedis.get
_orig_set = _MockRedis.set
_orig_del = _MockRedis.delete

def _inst_get(self, name):
    t0 = time.time()
    with tracer.start_as_current_span("redis.get", kind=SpanKind.CLIENT,
        attributes={"db.system": "redis", "db.operation": "GET",
                    "redis.key": name, "net.peer.name": self.host}) as span:
        value = _orig_get(self, name)
        hit   = value is not None
        span.set_attribute("redis.hit", hit)
        dur = (time.time() - t0) * 1000
        redis_ops.add(1,   attributes={"redis.command": "GET"})
        redis_latency.record(dur, attributes={"redis.command": "GET"})
        (redis_hits if hit else redis_misses).add(1, attributes={"redis.db": str(self.db)})
        return value

def _inst_set(self, name, value, ex=None):
    t0 = time.time()
    with tracer.start_as_current_span("redis.set", kind=SpanKind.CLIENT,
        attributes={"db.system": "redis", "db.operation": "SET",
                    "redis.key": name, "redis.ttl_sec": ex or -1,
                    "net.peer.name": self.host}) as span:
        result = _orig_set(self, name, value, ex)
        dur = (time.time() - t0) * 1000
        redis_ops.add(1,   attributes={"redis.command": "SET"})
        redis_latency.record(dur, attributes={"redis.command": "SET"})
        return result

def _inst_del(self, *names):
    t0 = time.time()
    with tracer.start_as_current_span("redis.delete", kind=SpanKind.CLIENT,
        attributes={"db.system": "redis", "db.operation": "DEL",
                    "redis.keys_count": len(names), "net.peer.name": self.host}) as span:
        result = _orig_del(self, *names)
        redis_ops.add(1, attributes={"redis.command": "DEL"})
        redis_latency.record((time.time() - t0) * 1000, attributes={"redis.command": "DEL"})
        return result

_MockRedis.get    = _inst_get
_MockRedis.set    = _inst_set
_MockRedis.delete = _inst_del


def login(user_id, session_data):
    r = redis.Redis(host="redis.internal", db=1, decode_responses=True)
    existing = r.get(f"session:{user_id}")
    if existing:
        logger.info("existing session found", extra={"auth.user_id": user_id,
                    "session.reuse": True})
        return json.loads(existing)

    session = {"session_id": uuid.uuid4().hex, "user_id": user_id, **session_data}
    r.set(f"session:{user_id}", json.dumps(session), ex=3600)
    logger.info("new session created", extra={"auth.user_id": user_id,
                "session.id": session["session_id"], "session.ttl_sec": 3600})
    return session

def logout(user_id):
    r = redis.Redis(host="redis.internal", db=1, decode_responses=True)
    r.delete(f"session:{user_id}")
    logger.info("session deleted", extra={"auth.user_id": user_id})


users = [
    ("USR-001", {"role": "admin",  "tier": "enterprise", "region": "us-east"}),
    ("USR-002", {"role": "viewer", "tier": "free",       "region": "eu-west"}),
    ("USR-003", {"role": "editor", "tier": "pro",        "region": "us-west"}),
]

print(f"\n[{SVC}] Session cache operations via patched redis-py...")
for user_id, data in users:
    sess = login(user_id, data)
    print(f"  ✅ login  {user_id}  session={sess['session_id'][:12]}...")
    login(user_id, data)  # second call — should hit cache

logout("USR-002")
print(f"  ✅ logout USR-002  session deleted")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
