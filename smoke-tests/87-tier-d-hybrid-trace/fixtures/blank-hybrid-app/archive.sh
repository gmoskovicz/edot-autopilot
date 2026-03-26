#!/usr/bin/env bash
# archive.sh — legacy archiving script (Tier D component)
#
# No observability. Run `Observe this project.` to add it.
#
# This script archives an order to the legacy storage system.
# It should emit a sidecar span as a child of the calling Flask span.
# The TRACEPARENT env var (set by the Flask app) must be forwarded
# to the sidecar so the span appears connected in Elastic.
#
# Usage: bash archive.sh <order_id>

ORDER_ID="${1:-ORD-UNKNOWN}"
SIDECAR_URL="${SIDECAR_URL:-http://127.0.0.1:9411}"

# Simulate archiving work
sleep 0.05
echo "Archived order ${ORDER_ID} to legacy storage"

# TODO: emit telemetry via sidecar (agent will add this)
# The agent must:
#   1. Call sidecar with action=start_span, passing TRACEPARENT
#   2. Do the archiving work
#   3. Call sidecar with action=end_span
# Without this, the archive step is invisible in Elastic APM.

exit 0
