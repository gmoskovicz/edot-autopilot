"""
Healthcare Appointment Sync — aiohttp Web Server

No observability. Run `Observe this project.` to add it.

Synchronises patient appointments from legacy scheduling systems (Cerner, Epic)
to a cloud calendar. Detects and resolves scheduling conflicts.
"""

import os
import uuid
import asyncio
import logging
import random

from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def upsert_appointment(patient_id: str, appointment: dict,
                             source_system: str) -> bool:
    """
    Write a single appointment to the cloud calendar.
    Returns True on success, False if a conflict was detected.
    """
    await asyncio.sleep(0.01)  # simulated cloud API call
    has_conflict = random.random() < 0.2
    if has_conflict:
        logger.warning(
            "appointment sync conflict resolved",
            extra={"patient_id": patient_id,
                   "appointment_id": appointment["id"],
                   "appointment_type": appointment["type"],
                   "source_system": source_system},
        )
    else:
        logger.info(
            "appointment synced",
            extra={"patient_id": patient_id,
                   "appointment_id": appointment["id"],
                   "appointment_type": appointment["type"]},
        )
    return not has_conflict


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def sync_appointments(request: web.Request) -> web.Response:
    """
    POST /api/sync/appointments

    Body (JSON):
        patient_id    (str)  — patient identifier
        source_system (str)  — legacy system name ('legacy-cerner' | 'legacy-epic')
        appointments  (list) — list of appointment objects, each with 'id' and 'type'

    Responses:
        200 — sync completed; returns synced + conflicts counts
        400 — missing required fields
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)

    patient_id    = body.get("patient_id")
    source_system = body.get("source_system")
    appointments  = body.get("appointments", [])

    if not patient_id or not source_system:
        return web.json_response({"error": "missing required fields"}, status=400)

    synced    = 0
    conflicts = 0

    for appt in appointments:
        success = await upsert_appointment(patient_id, appt, source_system)
        if success:
            synced += 1
        else:
            conflicts += 1

    logger.info(
        "patient appointment sync complete",
        extra={"patient_id": patient_id, "source_system": source_system,
               "synced": synced, "conflicts": conflicts,
               "total": len(appointments)},
    )

    return web.json_response({"status": 200, "synced": synced, "conflicts": conflicts})


def create_app() -> web.Application:
    application = web.Application()
    application.router.add_get("/health", health)
    application.router.add_post("/api/sync/appointments", sync_appointments)
    return application


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app = create_app()
    logger.info(f"Appointment sync service listening on port {port}")
    web.run_app(app, host="0.0.0.0", port=port)
