# Video Transcoding Job Submission — blank fixture

A Python service that submits video transcoding jobs to a Celery task queue.

## What it does

- Accepts a video file and a list of target formats (mp4, hls, webm)
- Submits one `apply_async` call per output format to the `media` queue
- Each job carries the video ID, output format, and quality setting

## SDK used

**Celery** — a distributed task queue framework. Uses
`Task.apply_async(args, kwargs, queue=...)` to enqueue work to a broker
(typically RabbitMQ or Redis).

Since no broker is available, a mock Task class is used that simulates the
same interface and returns a mock `AsyncResult` with a UUID task ID.

## No observability

This app has no OpenTelemetry instrumentation. Run:

```
Observe this project.
```

The agent should assign **Tier C** (monkey-patch) because Celery's OTel
instrumentation is limited and does not cover the producer side with standard
`SpanKind.CLIENT` semantics. It should wrap `Task.apply_async` with spans
carrying `celery.task_name`, `celery.queue`, and `celery.task_id` attributes.
