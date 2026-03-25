"""
Video Transcoding Job Submission — Celery

No observability. Run `Observe this project.` to add it.
"""

import uuid
import time


# ── Mock Celery (simulates real Celery without a broker) ───────────────────────

class _MockAsyncResult:
    def __init__(self, task_id):
        self.id = task_id


class _MockTask:
    name = "video.transcode"
    queue = "media"

    def apply_async(self, args=None, kwargs=None, queue=None, countdown=None, **opts):
        time.sleep(0.01)
        return _MockAsyncResult(str(uuid.uuid4()))


class celery:
    class app:
        class task:
            Task = _MockTask


# ── Application code ───────────────────────────────────────────────────────────

transcode = celery.app.task.Task()
transcode.name = "video.transcode"


def submit_transcode_job(video_id, output_format, quality="high"):
    """Submit a video transcode job to the Celery media queue."""
    result = transcode.apply_async(
        args=[video_id],
        kwargs={"output_format": output_format, "quality": quality},
        queue="media",
    )
    print(f"  Queued: {video_id} → {output_format} (task_id={result.id})")
    return result


if __name__ == "__main__":
    videos = [
        {"video_id": "VID-001", "source_format": "mov",
         "target_formats": ["mp4", "hls", "webm"], "customer": "CUST-ENT-001"},
        {"video_id": "VID-002", "source_format": "avi",
         "target_formats": ["mp4", "hls"], "customer": "CUST-PRO-042"},
        {"video_id": "VID-003", "source_format": "webm",
         "target_formats": ["mp4"], "customer": "CUST-FREE-007"},
    ]

    for video in videos:
        for fmt in video["target_formats"]:
            submit_transcode_job(video["video_id"], fmt)

    print("All transcode jobs submitted")
