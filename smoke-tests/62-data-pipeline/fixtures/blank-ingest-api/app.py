"""
Ingest API — Real-Time Data Pipeline (Flask)

No observability. Run `Observe this project.` to add OpenTelemetry.

This is the entry point of a 7-service data ingestion pipeline. Downstream:
  - schema-validator    — validates JSON schema
  - dedup-service       — detects duplicate events
  - transform-worker    — applies transformations
  - enrichment-service  — adds geo, user-agent context
  - storage-writer      — writes to data lake (S3/GCS)
  - search-indexer      — indexes into Elasticsearch

Routes:
  GET  /health          — liveness probe
  POST /ingest          — ingest a batch of events
  GET  /ingest/{job_id} — get ingestion job status
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
jobs = {}


def call_schema_validator(events: list) -> dict:
    """Validate event schemas — rejects unknown fields."""
    time.sleep(random.uniform(0.005, 0.025))
    invalid = [i for i, e in enumerate(events) if not e.get("event_type")]
    if invalid:
        return {"ok": False, "invalid_indices": invalid, "reason": "missing_event_type"}
    return {"ok": True, "validated": len(events)}


def call_dedup_service(events: list) -> dict:
    """Deduplicate events by event_id."""
    time.sleep(random.uniform(0.010, 0.030))
    # Simulate 10% duplicate rate
    dedup_count = sum(1 for _ in events if random.random() < 0.10)
    return {"ok": True, "duplicates_removed": dedup_count, "unique": len(events) - dedup_count}


def call_transform_worker(events: list) -> dict:
    """Apply field transformations and normalization."""
    time.sleep(random.uniform(0.020, 0.060))
    # Simulate 8% transform exception
    if random.random() < 0.08:
        raise RuntimeError("transform-worker: schema mismatch in field 'timestamp'")
    return {"ok": True, "transformed": len(events)}


def call_enrichment_service(events: list) -> dict:
    """Enrich events with geo + user-agent context."""
    time.sleep(random.uniform(0.015, 0.050))
    # 5% timeout — proceed without enrichment
    if random.random() < 0.05:
        raise TimeoutError("enrichment-service: timeout after 50ms")
    return {"ok": True, "enriched": len(events)}


def call_storage_writer(events: list, job_id: str) -> dict:
    """Write events to data lake."""
    time.sleep(random.uniform(0.030, 0.100))
    # 2% backpressure
    if random.random() < 0.02:
        raise IOError("storage-writer: backpressure — queue full")
    return {"ok": True, "written": len(events), "path": f"s3://data-lake/events/{job_id}"}


def call_search_indexer(events: list, job_id: str) -> dict:
    """Index events into Elasticsearch."""
    time.sleep(random.uniform(0.020, 0.070))
    return {"ok": True, "indexed": len(events), "index": f"events-{uuid.uuid4().hex[:4]}"}


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/ingest", methods=["POST"])
def ingest():
    body   = request.get_json(force=True) or {}
    events = body.get("events", [])
    source = body.get("source", "unknown")

    if not events:
        return jsonify({"error": "events required"}), 400

    job_id = f"job_{uuid.uuid4().hex[:12]}"

    try:
        # Step 1: Schema validation
        validation = call_schema_validator(events)
        if not validation["ok"]:
            return jsonify({
                "error": "schema_validation_failed",
                "details": validation,
            }), 422

        # Step 2: Deduplication
        dedup = call_dedup_service(events)
        unique_count = dedup["unique"]

        # Step 3: Transform
        try:
            call_transform_worker(events)
        except RuntimeError as e:
            logger.error("Transform failed for job %s: %s", job_id, e)
            return jsonify({"error": "transform_failed", "detail": str(e)}), 500

        # Step 4: Enrich (best-effort)
        try:
            call_enrichment_service(events)
        except TimeoutError:
            logger.warning("Enrichment timeout for job %s — proceeding", job_id)

        # Step 5: Store
        try:
            storage = call_storage_writer(events, job_id)
        except IOError as e:
            logger.error("Storage backpressure for job %s: %s", job_id, e)
            return jsonify({"error": "storage_backpressure", "detail": str(e)}), 503

        # Step 6: Index
        call_search_indexer(events, job_id)

        jobs[job_id] = {
            "job_id": job_id,
            "source": source,
            "events_received": len(events),
            "events_unique": unique_count,
            "status": "completed",
            "storage_path": storage["path"],
        }

        logger.info("Ingest complete: job=%s source=%s events=%d",
                    job_id, source, len(events))

        return jsonify(jobs[job_id]), 201

    except Exception as e:
        logger.exception("Unexpected error in ingest job %s", job_id)
        jobs[job_id] = {"job_id": job_id, "status": "failed", "error": str(e)}
        return jsonify({"error": "internal_error", "job_id": job_id}), 500


@app.route("/ingest/<job_id>")
def get_job(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify(job)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 6002))
    app.run(host="0.0.0.0", port=port, debug=False)
