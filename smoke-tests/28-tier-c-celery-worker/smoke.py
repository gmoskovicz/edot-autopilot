#!/usr/bin/env python3
"""
Smoke test: Tier C — Celery Task.apply_async() (monkey-patched library side).

Patches celery.app.task.Task.apply_async — existing call sites unchanged.
Business scenario: Video transcoding job submission.

Run:
    cd smoke-tests && python3 28-tier-c-celery-worker/smoke.py
"""

import os, sys, uuid, time
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-c-celery-worker"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

tasks_queued = meter.create_counter("celery.tasks_queued")
task_latency = meter.create_histogram("celery.enqueue_ms", unit="ms")


class _MockAsyncResult:
    def __init__(self, task_id):
        self.id = task_id

class _MockTask:
    name  = "video.transcode"
    queue = "media"

    def apply_async(self, args=None, kwargs=None, queue=None, countdown=None, **opts):
        time.sleep(0.01)
        return _MockAsyncResult(str(uuid.uuid4()))

class celery:
    class app:
        class task:
            Task = _MockTask


_orig_apply_async = _MockTask.apply_async

def _inst_apply_async(self, args=None, kwargs=None, queue=None, countdown=None, **opts):
    t0 = time.time()
    q  = queue or self.queue
    with tracer.start_as_current_span("celery.apply_async", kind=SpanKind.CLIENT,
        attributes={"celery.task_name": self.name, "celery.queue": q,
                    "celery.countdown_sec": countdown or 0}) as span:
        result = _orig_apply_async(self, args, kwargs, queue=q, countdown=countdown, **opts)
        dur = (time.time() - t0) * 1000
        span.set_attribute("celery.task_id", result.id)
        tasks_queued.add(1, attributes={"celery.task_name": self.name, "celery.queue": q})
        task_latency.record(dur, attributes={"celery.task_name": self.name})
        logger.info("celery task enqueued",
                    extra={"celery.task_name": self.name, "celery.task_id": result.id,
                           "celery.queue": q})
        return result

_MockTask.apply_async = _inst_apply_async


transcode = celery.app.task.Task()
transcode.name = "video.transcode"

videos = [
    {"video_id": "VID-001", "source_format": "mov",  "target_formats": ["mp4", "hls", "webm"], "customer": "CUST-ENT-001"},
    {"video_id": "VID-002", "source_format": "avi",  "target_formats": ["mp4", "hls"],          "customer": "CUST-PRO-042"},
    {"video_id": "VID-003", "source_format": "webm", "target_formats": ["mp4"],                 "customer": "CUST-FREE-007"},
]

print(f"\n[{SVC}] Submitting video transcode jobs via patched celery.apply_async...")
for video in videos:
    for fmt in video["target_formats"]:
        result = transcode.apply_async(
            args=[video["video_id"]],
            kwargs={"output_format": fmt, "quality": "high"},
            queue="media",
        )
        print(f"  ✅ {video['video_id']}  → {fmt:<6}  task={result.id[:12]}...")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
