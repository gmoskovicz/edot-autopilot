#!/usr/bin/env python3
"""
Smoke test: Rails 7 — CMS API with Action Controller, Active Record, Sidekiq, Action Cable.

Services modeled:
  web-rails-cms-api → web-rails-sidekiq-worker

Scenarios:
  1. Action Controller: before_action auth → action → Active Record query → JSON
  2. Active Record N+1: posts.each { |p| p.author } → N+1 warning span event
  3. Active Job → Sidekiq: enqueue ImageProcessJob → worker → CarrierWave → S3
  4. Action Cable: WebSocket subscribe → broadcast → client receives
  5. Rails cache: read_multi → miss → DB fetch → write_multi
  6. ActiveModel callbacks: before_save → after_commit → touch → reindex Elasticsearch

Run:
    cd smoke-tests && python3 78-web-rails/smoke.py
"""

import os, sys, time, random, uuid
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap

from opentelemetry.trace import SpanKind, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.metrics import Observation

ENDPOINT = os.environ["ELASTIC_OTLP_ENDPOINT"]
API_KEY  = os.environ["ELASTIC_API_KEY"]
ENV      = os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test")

propagator = TraceContextTextMapPropagator()

RAILS_ATTRS = {
    "framework":              "rails",
    "rails.version":          "7.1.2",
    "ruby.version":           "3.2.2",
    "telemetry.sdk.name":     "opentelemetry-ruby",
    "telemetry.sdk.language": "ruby",
}

# ── Bootstrap ─────────────────────────────────────────────────────────────────
rails   = O11yBootstrap("web-rails-cms-api",      ENDPOINT, API_KEY, ENV, extra_resource_attrs=RAILS_ATTRS)
sidekiq = O11yBootstrap("web-rails-sidekiq-worker",ENDPOINT, API_KEY, ENV, extra_resource_attrs=RAILS_ATTRS)

# ── Metrics instruments ───────────────────────────────────────────────────────
req_total    = rails.meter.create_counter("rails.request",             description="Total Rails requests")
req_duration = rails.meter.create_histogram("rails.request.duration",  description="Rails request latency", unit="ms")
ar_queries   = rails.meter.create_counter("rails.db.query",            description="Active Record query count")

def _sidekiq_queue_depth_cb(options):
    yield Observation(random.randint(0, 120), {"queue": "default"})
    yield Observation(random.randint(0, 15),  {"queue": "critical"})

sidekiq.meter.create_observable_gauge(
    "sidekiq.queue_depth", [_sidekiq_queue_depth_cb],
    description="Sidekiq queue depth per queue")

SVC = "web-rails-cms-api"
print(f"\n[{SVC}] Sending traces + logs + metrics to {ENDPOINT.split('@')[-1].split('/')[0]}...")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 1 — Action Controller: before_action auth → action → Active Record → JSON
# ─────────────────────────────────────────────────────────────────────────────
try:
    t0 = time.time()

    with rails.tracer.start_as_current_span(
        "rails.action_controller.PostsController#index", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("rails.controller", "PostsController")
        span.set_attribute("rails.action", "index")
        span.set_attribute("rails.format", "json")
        span.set_attribute("http.request.method", "GET")
        span.set_attribute("http.route", "/api/v1/posts")

        with rails.tracer.start_as_current_span(
            "rails.before_action.authenticate_user!", kind=SpanKind.INTERNAL
        ) as ba_span:
            ba_span.set_attribute("rails.filter", "before_action")
            ba_span.set_attribute("rails.filter_name", "authenticate_user!")
            ba_span.set_attribute("auth.token_valid", True)
            time.sleep(random.uniform(0.003, 0.01))

        with rails.tracer.start_as_current_span(
            "rails.active_record.SELECT", kind=SpanKind.CLIENT
        ) as ar_span:
            ar_span.set_attribute("db.system.name", "postgresql")
            ar_span.set_attribute("db.operation.name", "SELECT")
            ar_span.set_attribute("db.query.text", "SELECT posts.* FROM posts WHERE published = $1 ORDER BY created_at DESC LIMIT $2")
            ar_span.set_attribute("active_record.table", "posts")
            ar_span.set_attribute("rails.db.adapter", "postgresql")
            ar_span.set_attribute("service.peer.name", "postgresql")
            t_ar = time.time()
            time.sleep(random.uniform(0.01, 0.05))
            ar_queries.add(1, {"table": "posts", "operation": "SELECT"})

        span.set_attribute("http.response.status_code", 200)
        span.set_attribute("response.record_count", random.randint(10, 50))

    dur_ms = (time.time() - t0) * 1000
    req_total.add(1, {"http.request.method": "GET", "rails.controller": "PostsController", "rails.action": "index"})
    req_duration.record(dur_ms, {"rails.controller": "PostsController"})
    rails.logger.info("PostsController#index rendered JSON", extra={"duration_ms": round(dur_ms, 2)})
    print("  ✅ Scenario 1 — Action Controller before_action → action → Active Record → JSON")
except Exception as exc:
    print(f"  ❌ Scenario 1 — Action Controller: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 2 — Active Record N+1: posts.each { |p| p.author } → N+1 warning event
# ─────────────────────────────────────────────────────────────────────────────
try:
    n_posts = random.randint(5, 15)
    t0 = time.time()

    with rails.tracer.start_as_current_span(
        "rails.action_controller.PostsController#show_feed", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("rails.controller", "PostsController")
        span.set_attribute("rails.action", "show_feed")
        span.set_attribute("rails.format", "json")
        span.set_attribute("http.request.method", "GET")

        # Initial posts query
        with rails.tracer.start_as_current_span(
            "rails.active_record.SELECT", kind=SpanKind.CLIENT
        ) as ar_span:
            ar_span.set_attribute("db.system.name", "postgresql")
            ar_span.set_attribute("db.operation.name", "SELECT")
            ar_span.set_attribute("db.query.text", "SELECT posts.* FROM posts LIMIT $1")
            ar_span.set_attribute("active_record.table", "posts")
            ar_span.set_attribute("service.peer.name", "postgresql")
            time.sleep(random.uniform(0.005, 0.015))
            ar_queries.add(1, {"table": "posts", "operation": "SELECT"})

        # N+1: one SELECT per post to fetch author
        span.add_event(
            "active_record.n_plus_one_detected",
            attributes={
                "active_record.n_plus_one_detected": True,
                "active_record.association": "Post#author",
                "active_record.n_queries": n_posts,
                "active_record.suggestion": "Use includes(:author) to eager-load",
            },
        )
        rails.logger.warning(
            "N+1 query detected: Post#author",
            extra={"n_queries": n_posts, "association": "Post#author"},
        )

        for i in range(n_posts):
            with rails.tracer.start_as_current_span(
                "rails.active_record.SELECT", kind=SpanKind.CLIENT
            ) as n1_span:
                n1_span.set_attribute("db.system.name", "postgresql")
                n1_span.set_attribute("db.operation.name", "SELECT")
                n1_span.set_attribute("db.query.text", "SELECT users.* FROM users WHERE users.id = $1 LIMIT 1")
                n1_span.set_attribute("active_record.table", "users")
                n1_span.set_attribute("active_record.n_plus_one", True)
                n1_span.set_attribute("service.peer.name", "postgresql")
                time.sleep(random.uniform(0.003, 0.01))
                ar_queries.add(1, {"table": "users", "operation": "SELECT"})

        span.set_attribute("http.response.status_code", 200)

    dur_ms = (time.time() - t0) * 1000
    req_total.add(1, {"http.request.method": "GET", "rails.controller": "PostsController", "rails.action": "show_feed"})
    req_duration.record(dur_ms, {"rails.controller": "PostsController"})
    print(f"  ⚠️  Scenario 2 — Active Record N+1 detected ({n_posts} extra queries for Post#author)")
except Exception as exc:
    print(f"  ❌ Scenario 2 — Active Record N+1: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 3 — Active Job → Sidekiq: enqueue → worker → CarrierWave → S3
# ─────────────────────────────────────────────────────────────────────────────
try:
    job_id     = uuid.uuid4().hex
    post_id    = random.randint(100, 9999)
    carrier    = {}

    with rails.tracer.start_as_current_span(
        "rails.active_job.enqueue", kind=SpanKind.PRODUCER
    ) as span:
        span.set_attribute("messaging.system", "sidekiq")
        span.set_attribute("messaging.destination.name", "default")
        span.set_attribute("messaging.operation.type", "publish")
        span.set_attribute("active_job.job_class", "ImageProcessJob")
        span.set_attribute("active_job.job_id", job_id)
        span.set_attribute("active_job.queue_name", "default")
        span.set_attribute("post.id", post_id)
        span.set_attribute("service.peer.name", "sidekiq")
        propagator.inject(carrier)
        time.sleep(random.uniform(0.002, 0.008))

    rails.logger.info("ImageProcessJob enqueued", extra={"job_id": job_id, "post_id": post_id})

    with sidekiq.tracer.start_as_current_span(
        "sidekiq.perform", kind=SpanKind.CONSUMER
    ) as span:
        span.set_attribute("messaging.system", "sidekiq")
        span.set_attribute("messaging.operation.type", "process")
        span.set_attribute("sidekiq.queue", "default")
        span.set_attribute("sidekiq.retry_count", 0)
        span.set_attribute("active_job.job_class", "ImageProcessJob")
        span.set_attribute("active_job.job_id", job_id)
        span.set_attribute("post.id", post_id)

        with sidekiq.tracer.start_as_current_span(
            "carrierwave.process_image", kind=SpanKind.INTERNAL
        ) as cw_span:
            cw_span.set_attribute("carrierwave.uploader", "ImageUploader")
            cw_span.set_attribute("image.format", "jpeg")
            cw_span.set_attribute("image.resize_to", "800x600")
            time.sleep(random.uniform(0.05, 0.15))

        with sidekiq.tracer.start_as_current_span(
            "s3.put_object", kind=SpanKind.CLIENT
        ) as s3_span:
            s3_span.set_attribute("cloud.provider", "aws")
            s3_span.set_attribute("aws.s3.bucket", "cms-assets-prod")
            s3_span.set_attribute("aws.s3.key", f"posts/{post_id}/cover.jpg")
            s3_span.set_attribute("rpc.system", "aws-api")
            s3_span.set_attribute("rpc.service", "S3")
            s3_span.set_attribute("service.peer.name", "s3")
            time.sleep(random.uniform(0.03, 0.08))

    sidekiq.logger.info("ImageProcessJob completed", extra={"job_id": job_id, "post_id": post_id})
    print("  ✅ Scenario 3 — Active Job → Sidekiq → CarrierWave → S3")
except Exception as exc:
    print(f"  ❌ Scenario 3 — Active Job/Sidekiq: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 4 — Action Cable: WebSocket subscribe → broadcast → client receives
# ─────────────────────────────────────────────────────────────────────────────
try:
    channel  = "PostsChannel"
    room_id  = random.randint(1, 50)
    client_id = f"ws_{uuid.uuid4().hex[:6]}"

    with rails.tracer.start_as_current_span(
        "rails.action_cable.subscribe", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("action_cable.channel", channel)
        span.set_attribute("action_cable.room", room_id)
        span.set_attribute("websocket.client_id", client_id)
        span.set_attribute("messaging.system", "websocket")
        time.sleep(random.uniform(0.002, 0.008))

    with rails.tracer.start_as_current_span(
        "rails.action_cable.broadcast", kind=SpanKind.PRODUCER
    ) as span:
        span.set_attribute("action_cable.channel", channel)
        span.set_attribute("action_cable.room", room_id)
        span.set_attribute("messaging.system", "websocket")
        span.set_attribute("messaging.operation.type", "publish")
        span.set_attribute("broadcast.recipients", random.randint(1, 20))
        span.set_attribute("broadcast.payload_bytes", random.randint(128, 2048))
        time.sleep(random.uniform(0.002, 0.01))

    rails.logger.info("Action Cable broadcast sent", extra={"channel": channel, "room": room_id})
    print("  ✅ Scenario 4 — Action Cable subscribe → broadcast → client receives")
except Exception as exc:
    print(f"  ❌ Scenario 4 — Action Cable: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 5 — Rails cache: read_multi → miss → DB fetch → write_multi
# ─────────────────────────────────────────────────────────────────────────────
try:
    post_ids  = [random.randint(1, 500) for _ in range(5)]
    cache_keys = [f"post/{pid}/v1" for pid in post_ids]
    hit_ids    = random.sample(post_ids, k=random.randint(1, 3))
    miss_ids   = [pid for pid in post_ids if pid not in hit_ids]
    t0 = time.time()

    with rails.tracer.start_as_current_span(
        "rails.action_controller.PostsController#batch", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("rails.controller", "PostsController")
        span.set_attribute("rails.action", "batch")
        span.set_attribute("http.request.method", "GET")

        with rails.tracer.start_as_current_span(
            "rails.cache.read_multi", kind=SpanKind.CLIENT
        ) as cache_span:
            cache_span.set_attribute("cache.keys_requested", len(cache_keys))
            cache_span.set_attribute("cache.hits", len(hit_ids))
            cache_span.set_attribute("cache.misses", len(miss_ids))
            cache_span.set_attribute("cache.backend", "redis")
            cache_span.set_attribute("service.peer.name", "redis")
            time.sleep(random.uniform(0.005, 0.015))

        if miss_ids:
            with rails.tracer.start_as_current_span(
                "rails.active_record.SELECT", kind=SpanKind.CLIENT
            ) as ar_span:
                ar_span.set_attribute("db.system.name", "postgresql")
                ar_span.set_attribute("db.operation.name", "SELECT")
                ar_span.set_attribute("db.query.text", "SELECT posts.* FROM posts WHERE posts.id IN ($1, $2, $3)")
                ar_span.set_attribute("active_record.table", "posts")
                ar_span.set_attribute("active_record.ids_fetched", len(miss_ids))
                ar_span.set_attribute("service.peer.name", "postgresql")
                time.sleep(random.uniform(0.01, 0.04))
                ar_queries.add(1, {"table": "posts", "operation": "SELECT"})

            with rails.tracer.start_as_current_span(
                "rails.cache.write_multi", kind=SpanKind.CLIENT
            ) as write_span:
                write_span.set_attribute("cache.keys_written", len(miss_ids))
                write_span.set_attribute("cache.backend", "redis")
                write_span.set_attribute("cache.ttl_seconds", 300)
                write_span.set_attribute("service.peer.name", "redis")
                time.sleep(random.uniform(0.003, 0.01))

        span.set_attribute("http.response.status_code", 200)

    dur_ms = (time.time() - t0) * 1000
    req_total.add(1, {"http.request.method": "GET", "rails.controller": "PostsController", "rails.action": "batch"})
    req_duration.record(dur_ms, {"rails.controller": "PostsController"})
    rails.logger.info("Cache read_multi/write_multi completed",
                      extra={"hits": len(hit_ids), "misses": len(miss_ids)})
    print(f"  ✅ Scenario 5 — Rails cache read_multi (hits={len(hit_ids)}, misses={len(miss_ids)}) → DB → write_multi")
except Exception as exc:
    print(f"  ❌ Scenario 5 — Rails cache: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 6 — ActiveModel callbacks: before_save → after_commit → touch → reindex
# ─────────────────────────────────────────────────────────────────────────────
try:
    record_id = random.randint(1, 9999)

    with rails.tracer.start_as_current_span(
        "rails.action_controller.PostsController#create", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("rails.controller", "PostsController")
        span.set_attribute("rails.action", "create")
        span.set_attribute("rails.format", "json")
        span.set_attribute("http.request.method", "POST")

        with rails.tracer.start_as_current_span(
            "rails.active_model.callback.before_save", kind=SpanKind.INTERNAL
        ) as cb_span:
            cb_span.set_attribute("active_model.callback", "before_save")
            cb_span.set_attribute("active_model.model", "Post")
            cb_span.set_attribute("callback.method", "set_slug")
            time.sleep(random.uniform(0.001, 0.005))

        with rails.tracer.start_as_current_span(
            "rails.active_record.SELECT", kind=SpanKind.CLIENT
        ) as ar_span:
            ar_span.set_attribute("db.system.name", "postgresql")
            ar_span.set_attribute("db.operation.name", "INSERT")
            ar_span.set_attribute("db.query.text", "INSERT INTO posts (title, body, slug, author_id, created_at) VALUES ($1, $2, $3, $4, NOW()) RETURNING id")
            ar_span.set_attribute("active_record.table", "posts")
            ar_span.set_attribute("service.peer.name", "postgresql")
            time.sleep(random.uniform(0.01, 0.03))
            ar_queries.add(1, {"table": "posts", "operation": "INSERT"})

        with rails.tracer.start_as_current_span(
            "rails.active_model.callback.after_commit", kind=SpanKind.INTERNAL
        ) as cb_span:
            cb_span.set_attribute("active_model.callback", "after_commit")
            cb_span.set_attribute("active_model.model", "Post")

            with rails.tracer.start_as_current_span(
                "rails.active_record.touch", kind=SpanKind.CLIENT
            ) as touch_span:
                touch_span.set_attribute("db.system.name", "postgresql")
                touch_span.set_attribute("db.operation.name", "UPDATE")
                touch_span.set_attribute("active_record.table", "users")
                touch_span.set_attribute("active_record.association", "Post#author")
                touch_span.set_attribute("service.peer.name", "postgresql")
                time.sleep(random.uniform(0.003, 0.01))

            with rails.tracer.start_as_current_span(
                "elasticsearch.index", kind=SpanKind.CLIENT
            ) as es_span:
                es_span.set_attribute("db.system.name", "elasticsearch")
                es_span.set_attribute("db.operation.name", "index")
                es_span.set_attribute("elasticsearch.index", "posts_v2")
                es_span.set_attribute("elasticsearch.document_id", str(record_id))
                es_span.set_attribute("service.peer.name", "elasticsearch")
                time.sleep(random.uniform(0.01, 0.04))

        span.set_attribute("http.response.status_code", 201)
        span.set_attribute("post.id", record_id)

    rails.logger.info("Post created with full callback chain", extra={"post_id": record_id})
    print("  ✅ Scenario 6 — ActiveModel callbacks before_save → after_commit → touch → reindex ES")
except Exception as exc:
    print(f"  ❌ Scenario 6 — ActiveModel callbacks: {exc}")

# ── Flush all ─────────────────────────────────────────────────────────────────
rails.flush()
sidekiq.flush()

print(f"\n[{SVC}] Done. APM → {SVC} | Metrics: rails.request, sidekiq.queue_depth")
