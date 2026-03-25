"""
API Gateway — Auth & Identity Platform (Flask)

No observability. Run `Observe this project.` to add OpenTelemetry.

This is the API gateway for an auth/identity platform. Downstream services:
  - auth-service       (POST /auth/login, POST /auth/mfa)
  - user-directory     (GET  /users/{id})
  - token-service      (POST /tokens, POST /tokens/refresh)
  - session-store      (GET  /sessions/{id}, DELETE /sessions/{id})
  - audit-service      (POST /audit/events)

Routes:
  GET  /health             — liveness probe
  POST /api/v1/login       — authenticate user (password + MFA)
  POST /api/v1/logout      — invalidate session
  POST /api/v1/token/refresh — refresh access token
"""

import os
import uuid
import random
import logging
import time
from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── In-memory session store ────────────────────────────────────────────────────
sessions = {}

# ── Downstream stubs ───────────────────────────────────────────────────────────

def call_auth_service(username: str, password: str) -> dict:
    """POST /auth/login — validate credentials."""
    time.sleep(random.uniform(0.020, 0.060))
    if not username or not password:
        return {"ok": False, "reason": "missing_credentials"}
    # Simulate 15% wrong password
    if random.random() < 0.15:
        return {"ok": False, "reason": "invalid_password", "attempts": random.randint(1, 3)}
    # Simulate 8% account locked
    if random.random() < 0.08:
        return {"ok": False, "reason": "account_locked"}
    user_id = f"usr_{uuid.uuid4().hex[:8]}"
    return {"ok": True, "user_id": user_id, "requires_mfa": random.random() < 0.3}


def call_mfa_service(user_id: str, mfa_token: str) -> dict:
    """POST /auth/mfa — validate MFA token."""
    time.sleep(random.uniform(0.010, 0.040))
    # 8% MFA timeout
    if random.random() < 0.08:
        return {"ok": False, "reason": "mfa_timeout"}
    return {"ok": True}


def call_token_service(user_id: str) -> dict:
    """POST /tokens — issue JWT pair."""
    time.sleep(random.uniform(0.005, 0.020))
    access_token  = f"eyJ_{uuid.uuid4().hex[:32]}"
    refresh_token = f"ref_{uuid.uuid4().hex[:32]}"
    return {"access_token": access_token, "refresh_token": refresh_token,
            "expires_in": 3600}


def call_audit_service(event_type: str, user_id: str, ip_address: str) -> None:
    """POST /audit/events — log security event."""
    time.sleep(random.uniform(0.003, 0.012))


def call_session_store_delete(session_id: str) -> bool:
    """DELETE /sessions/{id} — invalidate session."""
    time.sleep(random.uniform(0.002, 0.010))
    return True


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/v1/login", methods=["POST"])
def login():
    body       = request.get_json(force=True) or {}
    username   = body.get("username", "")
    password   = body.get("password", "")
    mfa_token  = body.get("mfa_token")
    ip_address = request.remote_addr or "0.0.0.0"

    if not username or not password:
        return jsonify({"error": "username and password required"}), 400

    # Step 1: Authenticate
    auth_result = call_auth_service(username, password)
    if not auth_result["ok"]:
        reason = auth_result["reason"]
        call_audit_service("login_failed", username, ip_address)
        logger.warning("Login failed: user=%s reason=%s", username, reason)
        status_code = 423 if reason == "account_locked" else 401
        return jsonify({"error": reason}), status_code

    user_id = auth_result["user_id"]

    # Step 2: MFA (if required)
    if auth_result.get("requires_mfa"):
        if not mfa_token:
            return jsonify({"error": "mfa_required", "user_id": user_id}), 202
        mfa_result = call_mfa_service(user_id, mfa_token)
        if not mfa_result["ok"]:
            call_audit_service("mfa_failed", user_id, ip_address)
            return jsonify({"error": mfa_result["reason"]}), 401

    # Step 3: Issue tokens
    tokens = call_token_service(user_id)

    # Step 4: Store session
    session_id = str(uuid.uuid4())
    sessions[session_id] = {"user_id": user_id, "ip_address": ip_address}

    # Step 5: Audit success
    call_audit_service("login_success", user_id, ip_address)
    logger.info("Login successful: user=%s session=%s", user_id, session_id)

    return jsonify({
        "session_id":    session_id,
        "user_id":       user_id,
        "access_token":  tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "expires_in":    tokens["expires_in"],
    }), 200


@app.route("/api/v1/logout", methods=["POST"])
def logout():
    body       = request.get_json(force=True) or {}
    session_id = body.get("session_id")
    if not session_id or session_id not in sessions:
        return jsonify({"error": "invalid session"}), 401

    user_id = sessions.pop(session_id, {}).get("user_id", "unknown")
    call_session_store_delete(session_id)
    call_audit_service("logout", user_id, request.remote_addr or "0.0.0.0")
    logger.info("Logout: user=%s session=%s", user_id, session_id)
    return jsonify({"status": "logged_out"})


@app.route("/api/v1/token/refresh", methods=["POST"])
def refresh_token():
    body          = request.get_json(force=True) or {}
    refresh_token = body.get("refresh_token")
    if not refresh_token:
        return jsonify({"error": "refresh_token required"}), 400
    # Simulate 5% token expired
    if random.random() < 0.05:
        return jsonify({"error": "token_expired"}), 401
    user_id = f"usr_{uuid.uuid4().hex[:8]}"
    tokens  = call_token_service(user_id)
    return jsonify(tokens)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 6001))
    app.run(host="0.0.0.0", port=port, debug=False)
