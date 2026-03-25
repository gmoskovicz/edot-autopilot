"""
Auth Session Service — Redis Session Cache

No observability. Run `Observe this project.` to add it.
"""

import os
import uuid
import json
import logging

import redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_HOST = os.environ.get("REDIS_HOST", "redis.internal")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
SESSION_TTL = int(os.environ.get("SESSION_TTL_SEC", 3600))


# ── Session management functions ───────────────────────────────────────────────

def login(user_id: str, user_data: dict) -> dict:
    """
    Authenticate a user and create (or reuse) a session.

    Checks Redis for an existing session first. If found, returns the cached
    session. If not found, creates a new session and stores it in Redis with
    a TTL.
    """
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=True)
    session_key = f"session:{user_id}"

    existing = r.get(session_key)
    if existing:
        logger.info(
            f"Existing session found for user {user_id}",
            extra={"auth.user_id": user_id, "session.reuse": True},
        )
        return json.loads(existing)

    session = {
        "session_id": uuid.uuid4().hex,
        "user_id": user_id,
        **user_data,
    }
    r.set(session_key, json.dumps(session), ex=SESSION_TTL)
    logger.info(
        f"New session created for user {user_id}",
        extra={
            "auth.user_id": user_id,
            "session.id": session["session_id"],
            "session.ttl_sec": SESSION_TTL,
        },
    )
    return session


def logout(user_id: str) -> None:
    """
    Invalidate a user's session by deleting it from Redis.
    """
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=True)
    session_key = f"session:{user_id}"
    r.delete(session_key)
    logger.info(
        f"Session deleted for user {user_id}",
        extra={"auth.user_id": user_id},
    )


def get_session(user_id: str) -> dict | None:
    """
    Look up an active session without creating one.
    Returns None if the session doesn't exist or has expired.
    """
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=True)
    session_key = f"session:{user_id}"
    data = r.get(session_key)
    if data:
        return json.loads(data)
    return None


def refresh_session(user_id: str) -> bool:
    """
    Extend the TTL on an existing session (sliding window expiry).
    Returns True if the session existed and was refreshed, False otherwise.
    """
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=True)
    session_key = f"session:{user_id}"
    if r.exists(session_key):
        r.expire(session_key, SESSION_TTL)
        logger.info(
            f"Session TTL refreshed for user {user_id}",
            extra={"auth.user_id": user_id, "session.ttl_sec": SESSION_TTL},
        )
        return True
    return False


# ── Sample run (used in local dev / smoke test) ───────────────────────────────
USERS = [
    ("USR-001", {"role": "admin",  "tier": "enterprise", "region": "us-east"}),
    ("USR-002", {"role": "viewer", "tier": "free",       "region": "eu-west"}),
    ("USR-003", {"role": "editor", "tier": "pro",        "region": "us-west"}),
]

if __name__ == "__main__":
    print("Creating sessions...")
    for user_id, data in USERS:
        try:
            session = login(user_id, data)
            print(f"  {user_id}: new session={session['session_id']}")
        except Exception as e:
            print(f"  {user_id}: ERROR — {e}")

    print("Reusing sessions (cache hit)...")
    for user_id, data in USERS:
        try:
            session = login(user_id, data)
            print(f"  {user_id}: reused session={session['session_id']}")
        except Exception as e:
            print(f"  {user_id}: ERROR — {e}")

    print("Logging out USR-002...")
    logout("USR-002")

    print("Verifying USR-002 session is gone...")
    s = get_session("USR-002")
    print(f"  USR-002 session: {s}")
