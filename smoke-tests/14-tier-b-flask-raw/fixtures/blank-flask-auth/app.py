"""
User Authentication Service — Flask REST API with MFA

No observability. Run `Observe this project.` to add it.

Handles user login with two-factor authentication: validates credentials,
dispatches a one-time password via the user's chosen MFA channel (SMS, email,
or TOTP), and issues a session token.
"""

import os
import uuid
import time
import logging

from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


# ── Simulated user store ───────────────────────────────────────────────────────
# In production this queries the user DB.
def validate_credentials(user_id: str, password_hash: str) -> bool:
    """Return True if the password hash is valid for this user."""
    time.sleep(0.02)  # simulated DB lookup latency
    return password_hash.startswith("hash_")


def send_otp(user_id: str, mfa_channel: str) -> str:
    """
    Dispatch a one-time password via SMS, email, or TOTP.
    Returns the OTP identifier for tracking.
    """
    time.sleep(0.05)  # simulated SMS/email gateway latency
    otp_id = f"OTP-{uuid.uuid4().hex[:8].upper()}"
    logger.info(
        "OTP dispatched",
        extra={"user_id": user_id, "mfa_channel": mfa_channel, "otp_id": otp_id},
    )
    return otp_id


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/auth/login", methods=["POST"])
def login():
    """
    POST /auth/login

    Body:
        user_id       (str)  — user account identifier
        password_hash (str)  — pre-hashed credential
        mfa_channel   (str)  — 'sms' | 'email' | 'totp'

    Responses:
        200  — credentials valid; MFA OTP dispatched; session created
        401  — invalid credentials
    """
    body = request.get_json(force=True)
    user_id       = body.get("user_id", "anon")
    password_hash = body.get("password_hash", "")
    mfa_channel   = body.get("mfa_channel", "sms")

    valid = validate_credentials(user_id, password_hash)
    if not valid:
        logger.warning(
            "login failed: invalid credentials",
            extra={"user_id": user_id, "mfa_channel": mfa_channel},
        )
        return jsonify({"error": "invalid_credentials"}), 401

    otp_id     = send_otp(user_id, mfa_channel)
    session_id = f"sess_{uuid.uuid4().hex}"

    logger.info(
        "login: MFA OTP dispatched",
        extra={"user_id": user_id, "mfa_channel": mfa_channel,
               "otp_id": otp_id, "session_id": session_id},
    )
    return jsonify({
        "session_id":   session_id,
        "mfa_required": True,
        "otp_id":       otp_id,
    }), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
