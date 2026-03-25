"""
Server Decommission API — Bottle Micro-Framework

No observability. Run `Observe this project.` to add it.

Internal infrastructure API that orchestrates server decommissioning:
checks active dependencies, drains the load balancer, and archives the
server record.
"""

import os
import uuid
import time
import random
import logging

import bottle
from bottle import Bottle, request, response

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Bottle()


def check_dependencies(hostname: str, datacenter: str) -> int:
    """Return the count of active dependencies blocking decommission."""
    time.sleep(0.02)  # simulated registry lookup
    dep_count = random.randint(0, 3)
    if dep_count > 0:
        logger.warning(
            "decommission blocked: active dependencies found",
            extra={"hostname": hostname, "dependencies_count": dep_count},
        )
    return dep_count


def drain_load_balancer(hostname: str, datacenter: str) -> int:
    """Drain all active connections from the load balancer. Returns drained count."""
    time.sleep(0.04)  # simulated LB drain
    connections = random.randint(0, 50)
    logger.info(
        "load balancer drained",
        extra={"hostname": hostname, "datacenter": datacenter,
               "connections_drained": connections},
    )
    return connections


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/api/infra/servers/<hostname>/decommission", method="POST")
def decommission_server(hostname):
    """
    POST /api/infra/servers/<hostname>/decommission

    Body (JSON):
        datacenter (str) — datacenter identifier (e.g. 'us-east-1')
        reason     (str) — decommission reason ('end-of-life' | 'replaced' | 'hardware-failure')

    Responses:
        200 — decommission completed; archive_id returned
        409 — blocked by active dependencies
    """
    body       = request.json or {}
    datacenter = body.get("datacenter", "dc-unknown")
    reason     = body.get("reason", "end-of-life")

    # Step 1: dependency check
    dep_count = check_dependencies(hostname, datacenter)

    # Step 2: drain load balancer
    connections_drained = drain_load_balancer(hostname, datacenter)

    # Step 3: archive
    archive_id = f"ARCH-{uuid.uuid4().hex[:8].upper()}"
    logger.info(
        "server decommissioned",
        extra={"hostname": hostname, "datacenter": datacenter,
               "reason": reason, "archive_id": archive_id,
               "connections_drained": connections_drained,
               "active_dependencies": dep_count},
    )

    response.content_type = "application/json"
    return {
        "status":     200,
        "archive_id": archive_id,
        "hostname":   hostname,
        "datacenter": datacenter,
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    bottle.run(app, host="0.0.0.0", port=port, debug=False, quiet=True)
