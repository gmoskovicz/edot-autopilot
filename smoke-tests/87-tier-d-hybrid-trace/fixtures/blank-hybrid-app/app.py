"""
Hybrid Service — Flask API + Shell Script subprocess

No observability. Run `Observe this project.` to add it.

This service handles order processing. For each order it:
1. Validates the request (Flask handler — Tier A candidate)
2. Runs a shell script that calls an external archiving system
   (the shell script is a Tier D component — no OTel SDK available)

The observability challenge: both components must appear in the SAME
trace in Elastic. The Flask span must pass its traceparent to the shell
script so the sidecar spans are connected as children, not orphans.
"""

import os
import subprocess
import logging

from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

ARCHIVE_SCRIPT = os.path.join(os.path.dirname(__file__), "archive.sh")


def run_archive(order_id: str, traceparent: str = "") -> dict:
    """
    Run the archive shell script as a subprocess.
    Pass the traceparent so the script's sidecar calls are child spans.
    """
    env = os.environ.copy()
    if traceparent:
        env["TRACEPARENT"] = traceparent

    result = subprocess.run(
        ["bash", ARCHIVE_SCRIPT, order_id],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/orders", methods=["POST"])
def create_order():
    body = request.get_json(force=True)
    order_id = body.get("order_id", "ORD-001")
    customer_id = body.get("customer_id", "CUST-001")
    amount_usd = float(body.get("amount_usd", 0.0))

    if amount_usd <= 0:
        return jsonify({"error": "amount must be > 0"}), 400

    # Archive via shell script (Tier D component)
    # No traceparent passed yet — observability gap to be fixed by the agent
    archive_result = run_archive(order_id)

    logger.info("Order created", extra={
        "order_id": order_id,
        "customer_id": customer_id,
        "amount_usd": amount_usd,
        "archive_exit_code": archive_result["exit_code"],
    })

    return jsonify({
        "order_id": order_id,
        "status": "confirmed",
        "amount_usd": amount_usd,
        "archive": archive_result,
    }), 201


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
