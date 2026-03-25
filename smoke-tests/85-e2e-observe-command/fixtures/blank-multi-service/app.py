"""
Multi-Service App — Flask + Redis cache + external HTTP dependency

No observability. Run `Observe this project.` to add it.

A Flask application that uses Redis for caching and makes external HTTP calls.
Typical microservice pattern: cache-aside for hot data, external API calls for
enrichment. Cache miss rate is a key SLO: p99 cache reads < 10ms.
"""

import os
import json
import logging
import time
import requests

from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── Mock Redis client ──────────────────────────────────────────────────────────
# In production: import redis; r = redis.Redis(host=..., port=6379)
# We simulate it with an in-process dict so tests don't need a real Redis.

class _MockRedis:
    """Simulates redis.Redis — same interface used in production code."""
    def __init__(self):
        self._store: dict = {}
        self._ttls:  dict = {}

    def set(self, key: str, value: str, ex: int = None) -> bool:
        self._store[key] = value
        if ex:
            self._ttls[key] = time.time() + ex
        return True

    def get(self, key: str):
        if key in self._ttls and time.time() > self._ttls[key]:
            del self._store[key]
            del self._ttls[key]
            return None
        return self._store.get(key)

    def delete(self, key: str) -> int:
        removed = int(key in self._store)
        self._store.pop(key, None)
        self._ttls.pop(key, None)
        return removed

    def ping(self) -> bool:
        return True


redis_client = _MockRedis()

CACHE_TTL_SECONDS   = 300   # 5 minutes
EXTERNAL_API_TIMEOUT = 5    # seconds

EXTERNAL_API_URL = os.environ.get(
    "EXTERNAL_API_URL", "https://httpbin.org/json"
)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    try:
        redis_client.ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return jsonify({"status": "ok", "redis": "ok" if redis_ok else "degraded"})


@app.route("/cache/set", methods=["POST"])
def cache_set():
    body  = request.get_json(force=True)
    key   = body.get("key")
    value = body.get("value")
    ttl   = body.get("ttl", CACHE_TTL_SECONDS)

    if not key:
        return jsonify({"error": "key is required"}), 400
    if value is None:
        return jsonify({"error": "value is required"}), 400

    serialized = json.dumps(value) if not isinstance(value, str) else value
    redis_client.set(key, serialized, ex=ttl)
    logger.info(f"Cache set: key={key!r} ttl={ttl}s")
    return jsonify({"key": key, "stored": True, "ttl": ttl})


@app.route("/cache/get/<key>", methods=["GET"])
def cache_get(key):
    raw = redis_client.get(key)
    if raw is None:
        logger.info(f"Cache miss: key={key!r}")
        return jsonify({"key": key, "hit": False, "value": None}), 200

    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        value = raw

    logger.info(f"Cache hit: key={key!r}")
    return jsonify({"key": key, "hit": True, "value": value})


@app.route("/fetch", methods=["GET"])
def fetch_external():
    """Fetch data from an external HTTP API (demonstrating outbound HTTP tracing)."""
    url = request.args.get("url", EXTERNAL_API_URL)
    logger.info(f"Fetching external URL: {url}")

    # Cache-aside: check cache first
    cache_key = f"fetch:{url}"
    cached = redis_client.get(cache_key)
    if cached:
        logger.info(f"Serving from cache: {url}")
        return jsonify({"source": "cache", "data": json.loads(cached)})

    # On cache miss, make the real HTTP call
    try:
        resp = requests.get(url, timeout=EXTERNAL_API_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.Timeout:
        logger.error(f"External API timeout: {url}")
        return jsonify({"error": "external API timeout"}), 504
    except requests.RequestException as e:
        logger.error(f"External API error: {e}")
        return jsonify({"error": str(e)}), 502

    # Store in cache
    redis_client.set(cache_key, json.dumps(data), ex=CACHE_TTL_SECONDS)
    return jsonify({"source": "api", "data": data})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
