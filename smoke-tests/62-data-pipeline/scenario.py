#!/usr/bin/env python3
"""
Real-Time Data Ingestion Pipeline — Distributed Tracing Scenario
=================================================================

Services modeled:
  ingest-api → schema-validator
             → dedup-service
             → transform-worker
             → enrichment-service
             → storage-writer
             → search-indexer

25 trace scenarios with realistic error mix:
  60% clean ingest (all stages pass)
  15% schema validation failure
  10% duplicate detected
   8% transform exception
   5% enrichment timeout (proceed without enrichment)
   2% storage backpressure (retry after backoff)

Run:
    cd smoke-tests
    python3 62-data-pipeline/scenario.py
"""

import os, sys, uuid, time, random, json
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

ENDPOINT = os.environ["ELASTIC_OTLP_ENDPOINT"]
API_KEY  = os.environ["ELASTIC_API_KEY"]
ENV      = os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test")

propagator = TraceContextTextMapPropagator()

# ── Per-service O11y bootstrap ────────────────────────────────────────────────
ingest    = O11yBootstrap("ingest-api",          ENDPOINT, API_KEY, ENV)
schema    = O11yBootstrap("schema-validator",    ENDPOINT, API_KEY, ENV)
dedup     = O11yBootstrap("dedup-service",       ENDPOINT, API_KEY, ENV)
transform = O11yBootstrap("transform-worker",    ENDPOINT, API_KEY, ENV)
enrichment= O11yBootstrap("enrichment-service",  ENDPOINT, API_KEY, ENV)
storage   = O11yBootstrap("storage-writer",      ENDPOINT, API_KEY, ENV)
indexer   = O11yBootstrap("search-indexer",      ENDPOINT, API_KEY, ENV)

# ── Metrics instruments ───────────────────────────────────────────────────────
# ingest-api
ing_events      = ingest.meter.create_counter("events.ingested",          description="Events received by ingest API")
ing_rejected    = ingest.meter.create_counter("events.rejected",          description="Events rejected at any stage")
ing_latency     = ingest.meter.create_histogram("pipeline.latency_ms",    description="End-to-end pipeline latency", unit="ms")
ing_batch_size  = ingest.meter.create_histogram("ingest.batch_size",      description="Batch record count")

# schema-validator
sch_valid       = schema.meter.create_counter("schema.valid",             description="Records passing validation")
sch_invalid     = schema.meter.create_counter("schema.invalid",           description="Records failing validation")
sch_latency     = schema.meter.create_histogram("schema.validation_ms",   description="Validation latency", unit="ms")

# dedup-service
dup_checked     = dedup.meter.create_counter("dedup.checked",             description="Records checked for duplicates")
dup_rejected    = dedup.meter.create_counter("dedup.duplicates",          description="Duplicate records rejected")
dup_latency     = dedup.meter.create_histogram("dedup.lookup_ms",         description="Bloom filter lookup latency", unit="ms")

# transform-worker
trn_processed   = transform.meter.create_counter("transform.processed",   description="Records transformed")
trn_errors      = transform.meter.create_counter("transform.errors",      description="Transform failures")
trn_latency     = transform.meter.create_histogram("transform.duration_ms",description="Transform latency", unit="ms")

# enrichment-service
enr_enriched    = enrichment.meter.create_counter("enrichment.enriched",  description="Records enriched")
enr_timeouts    = enrichment.meter.create_counter("enrichment.timeouts",  description="Enrichment service timeouts")
enr_latency     = enrichment.meter.create_histogram("enrichment.duration_ms", description="Enrichment latency", unit="ms")

# storage-writer
sto_written     = storage.meter.create_counter("storage.records_written", description="Records written to storage")
sto_bytes       = storage.meter.create_histogram("storage.bytes_written", description="Bytes written per batch", unit="By")
sto_retries     = storage.meter.create_counter("storage.retries",         description="Storage write retries")

# search-indexer
idx_docs        = indexer.meter.create_counter("index.docs_indexed",      description="Documents indexed")
idx_latency     = indexer.meter.create_histogram("index.duration_ms",     description="Index operation latency", unit="ms")


# ── Event type definitions ─────────────────────────────────────────────────────
EVENT_TYPES  = ["clickstream", "purchase", "signup", "search", "error", "pageview", "api_call"]
EVENT_SOURCES= ["web", "mobile-ios", "mobile-android", "api", "sdk-python", "sdk-js"]
GEO_COUNTRIES= ["US", "GB", "DE", "FR", "JP", "CA", "AU", "BR", "IN", "SG", "NL", "SE"]
USER_SEGMENTS= ["new_user", "returning", "power_user", "enterprise", "trial", "churned"]

# JSON schema field definitions per event type
REQUIRED_FIELDS = {
    "clickstream": ["event_id", "user_id", "session_id", "url", "timestamp"],
    "purchase":    ["event_id", "user_id", "order_id", "amount", "currency", "timestamp"],
    "signup":      ["event_id", "user_id", "email", "plan", "timestamp"],
    "search":      ["event_id", "user_id", "query", "result_count", "timestamp"],
    "error":       ["event_id", "user_id", "error_code", "stack_trace", "timestamp"],
    "pageview":    ["event_id", "user_id", "page", "referrer", "timestamp"],
    "api_call":    ["event_id", "api_key", "endpoint", "method", "latency_ms", "timestamp"],
}

# S3 paths by event type
STORAGE_PATHS = {
    "clickstream": "s3://data-lake/events/clickstream/",
    "purchase":    "s3://data-lake/events/purchases/",
    "signup":      "s3://data-lake/events/signups/",
    "search":      "s3://data-lake/events/searches/",
    "error":       "s3://data-lake/events/errors/",
    "pageview":    "s3://data-lake/events/pageviews/",
    "api_call":    "s3://data-lake/events/api-calls/",
}


# ── Helper ─────────────────────────────────────────────────────────────────────
def inject_traceparent(span) -> str:
    sc = span.get_span_context()
    return f"00-{sc.trace_id:032x}-{sc.span_id:016x}-01"

def extract_context(tp: str):
    return propagator.extract({"traceparent": tp})

def make_batch(event_type: str, source: str, batch_size: int,
               corrupt: bool = False, duplicate: bool = False) -> dict:
    """Generate a synthetic event batch."""
    batch_id = f"BATCH-{uuid.uuid4().hex[:12].upper()}"
    events   = []
    for j in range(batch_size):
        ev = {
            "event_id":  str(uuid.uuid4()) if not (duplicate and j == 0) else "DUPE-0000-0000-0000",
            "user_id":   f"u_{uuid.uuid4().hex[:8]}",
            "session_id": f"s_{uuid.uuid4().hex[:10]}",
            "timestamp": int(time.time() * 1000) - random.randint(0, 5000),
            "source":    source,
            "event_type": event_type,
        }
        # Add type-specific fields
        if event_type == "clickstream":
            ev.update({"url": f"https://app.example.com/page-{random.randint(1,50)}",
                       "duration_ms": random.randint(100, 8000)})
        elif event_type == "purchase":
            ev.update({"order_id": f"ORD-{uuid.uuid4().hex[:8].upper()}",
                       "amount": round(random.uniform(9.99, 999.99), 2),
                       "currency": random.choice(["USD", "EUR", "GBP", "JPY"])})
        elif event_type == "search":
            ev.update({"query": random.choice(["python observability", "buy laptop",
                                               "how to", "pricing plans", "contact us"]),
                       "result_count": random.randint(0, 500)})
        elif event_type == "error":
            ev.update({"error_code": random.choice(["NullPointerException",
                                                     "ConnectionTimeoutError",
                                                     "OutOfMemoryError",
                                                     "SegmentationFault"]),
                       "stack_trace": "at main() line 42\n  at process() line 19"})

        if corrupt:
            # Remove a required field to cause schema failure
            req = REQUIRED_FIELDS.get(event_type, [])
            if req:
                ev.pop(random.choice(req[1:] or req), None)

        events.append(ev)

    return {
        "batch_id":    batch_id,
        "event_type":  event_type,
        "source":      source,
        "records":     events,
        "records_count": len(events),
        "schema_version": "2.1",
    }


# ── Service functions ──────────────────────────────────────────────────────────

def svc_schema_validator(batch_id: str, event_type: str, records: list,
                           parent_tp: str, corrupt: bool = False) -> tuple:
    """Validate JSON schema for all records in the batch."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()
    required = REQUIRED_FIELDS.get(event_type, [])

    with ingest.tracer.start_as_current_span(
        "http.client.schema_validator", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "schema-validator",
                    "http.url": "http://schema-validator/api/v1/validate",
                    "event.batch_id": batch_id, "event.type": event_type,
                    "records.count": len(records)}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with schema.tracer.start_as_current_span(
            "schema.validate_batch", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v1/validate",
                        "event.batch_id": batch_id, "event.type": event_type,
                        "schema.version": "2.1", "schema.strict_mode": True,
                        "records.count": len(records),
                        "schema.required_fields": ",".join(required)}
        ) as entry_span:
            time.sleep(random.uniform(0.01, 0.05))

            valid_count  = 0
            invalid_count= 0
            first_error  = None

            for rec in records:
                missing = [f for f in required if f not in rec]
                if missing or corrupt:
                    invalid_count += 1
                    if not first_error:
                        field = missing[0] if missing else required[-1]
                        first_error = f"MissingRequiredField: '{field}' in event_id={rec.get('event_id','?')}"
                else:
                    valid_count += 1

            dur_ms = (time.time() - t0) * 1000
            sch_valid.add(valid_count, attributes={"event.type": event_type})
            sch_latency.record(dur_ms, attributes={"event.type": event_type})

            entry_span.set_attribute("records.valid",    valid_count)
            entry_span.set_attribute("records.rejected", invalid_count)

            if invalid_count > 0:
                sch_invalid.add(invalid_count, attributes={"event.type": event_type})
                err = Exception(first_error)
                entry_span.record_exception(err)
                entry_span.set_status(StatusCode.ERROR, str(err))
                exit_span.record_exception(ValueError("schema_validation_failed"), attributes={"exception.escaped": True})
                exit_span.set_status(StatusCode.ERROR, "schema_validation_failed")
                schema.logger.error(
                    f"schema validation failed: {invalid_count}/{len(records)} records invalid",
                    extra={"event.batch_id": batch_id, "event.type": event_type,
                           "records.valid": valid_count, "records.rejected": invalid_count,
                           "schema.first_error": first_error}
                )
                raise err

            schema.logger.info(
                f"schema validation passed: {valid_count} records",
                extra={"event.batch_id": batch_id, "event.type": event_type,
                       "records.valid": valid_count, "schema.duration_ms": round(dur_ms, 2)}
            )
            return valid_count, inject_traceparent(entry_span)


def svc_dedup(batch_id: str, event_type: str, records: list,
               parent_tp: str, force_duplicate: bool = False) -> tuple:
    """Bloom-filter deduplication pass."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with ingest.tracer.start_as_current_span(
        "http.client.dedup_service", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "dedup-service",
                    "http.url": "http://dedup-service/api/v1/check",
                    "event.batch_id": batch_id, "records.count": len(records)}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with dedup.tracer.start_as_current_span(
            "dedup.check_batch", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v1/check",
                        "event.batch_id": batch_id, "event.type": event_type,
                        "dedup.backend": "redis-bloom", "dedup.false_positive_rate": 0.001,
                        "records.count": len(records)}
        ) as entry_span:
            time.sleep(random.uniform(0.005, 0.03))

            dup_count  = 0
            seen_ids   = set()
            if force_duplicate:
                dup_count = random.randint(1, min(3, len(records)))

            for i, rec in enumerate(records):
                eid = rec.get("event_id", "")
                if eid in seen_ids or (force_duplicate and i < dup_count):
                    dup_count = max(dup_count, i + 1)
                seen_ids.add(eid)

            unique_count = len(records) - dup_count
            dur_ms = (time.time() - t0) * 1000

            dup_checked.add(len(records), attributes={"event.type": event_type})
            dup_latency.record(dur_ms, attributes={"dedup.backend": "redis-bloom"})

            entry_span.set_attribute("dedup.duplicates_found", dup_count)
            entry_span.set_attribute("dedup.unique_records",   unique_count)
            entry_span.set_attribute("dedup.bloom_filter_size", 10_000_000)

            if force_duplicate and dup_count > 0:
                dup_rejected.add(dup_count, attributes={"event.type": event_type})
                err = Exception(f"DuplicateEventError: {dup_count} duplicate event_ids detected in batch {batch_id}")
                entry_span.record_exception(err)
                entry_span.set_status(StatusCode.ERROR, str(err))
                exit_span.record_exception(ValueError("duplicate_rejected"), attributes={"exception.escaped": True})
                exit_span.set_status(StatusCode.ERROR, "duplicate_rejected")
                dedup.logger.warning(
                    f"duplicates detected: {dup_count}/{len(records)} records rejected",
                    extra={"event.batch_id": batch_id, "event.type": event_type,
                           "dedup.duplicates_found": dup_count, "dedup.unique_records": unique_count}
                )
                raise err

            dedup.logger.info(
                f"dedup check passed: {unique_count} unique records",
                extra={"event.batch_id": batch_id, "event.type": event_type,
                       "dedup.duplicates_found": dup_count, "dedup.unique_records": unique_count,
                       "dedup.duration_ms": round(dur_ms, 2)}
            )
            return unique_count, inject_traceparent(entry_span)


def svc_transform(batch_id: str, event_type: str, source: str, records: list,
                   parent_tp: str, force_malformed: bool = False) -> tuple:
    """Normalize and field-map raw events."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with ingest.tracer.start_as_current_span(
        "http.client.transform_worker", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "transform-worker",
                    "http.url": "http://transform-worker/api/v1/transform",
                    "event.batch_id": batch_id, "event.type": event_type,
                    "records.count": len(records)}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with transform.tracer.start_as_current_span(
            "transform.normalize_batch", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v1/transform",
                        "event.batch_id": batch_id, "event.type": event_type,
                        "event.source": source, "transform.version": "v3.1.0",
                        "transform.mapping": f"{event_type}-to-canonical-v2",
                        "records.count": len(records)}
        ) as entry_span:
            time.sleep(random.uniform(0.02, 0.08))

            if force_malformed:
                err = Exception(
                    f"UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc3 "
                    f"in field 'user_agent' of event batch {batch_id}"
                )
                entry_span.record_exception(err)
                entry_span.set_status(StatusCode.ERROR, str(err))
                exit_span.record_exception(RuntimeError("transform_failed"), attributes={"exception.escaped": True})
                exit_span.set_status(StatusCode.ERROR, "transform_failed")
                trn_errors.add(1, attributes={"event.type": event_type, "error.type": "UnicodeDecodeError"})
                transform.logger.error(
                    f"transform failed: encoding error in batch {batch_id}",
                    extra={"event.batch_id": batch_id, "event.type": event_type,
                           "event.source": source, "transform.error": str(err)}
                )
                raise err

            # Simulate field mapping / normalization
            transformed_count = len(records)
            bytes_out = sum(len(json.dumps(r)) for r in records)

            dur_ms = (time.time() - t0) * 1000
            trn_processed.add(transformed_count, attributes={"event.type": event_type})
            trn_latency.record(dur_ms, attributes={"event.type": event_type})

            entry_span.set_attribute("transform.records_out",     transformed_count)
            entry_span.set_attribute("transform.bytes_out",       bytes_out)
            entry_span.set_attribute("transform.fields_mapped",   random.randint(5, 20))
            entry_span.set_attribute("transform.fields_dropped",  random.randint(0, 4))

            transform.logger.info(
                f"transform complete: {transformed_count} records normalized",
                extra={"event.batch_id": batch_id, "event.type": event_type,
                       "transform.records_out": transformed_count,
                       "transform.bytes_out": bytes_out,
                       "transform.duration_ms": round(dur_ms, 2)}
            )
            return transformed_count, bytes_out, inject_traceparent(entry_span)


def svc_enrichment(batch_id: str, event_type: str, records: list, source: str,
                    parent_tp: str, force_timeout: bool = False) -> tuple:
    """Geo-IP and user segment enrichment."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with ingest.tracer.start_as_current_span(
        "http.client.enrichment_service", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "enrichment-service",
                    "http.url": "http://enrichment-service/api/v2/enrich",
                    "event.batch_id": batch_id, "records.count": len(records)}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with enrichment.tracer.start_as_current_span(
            "enrichment.enrich_batch", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v2/enrich",
                        "event.batch_id": batch_id, "event.type": event_type,
                        "enrichment.providers": "maxmind-geoip2,segment-profiles",
                        "enrichment.geo_enabled": True,
                        "enrichment.segment_enabled": True,
                        "records.count": len(records)}
        ) as entry_span:
            if force_timeout:
                time.sleep(random.uniform(3.5, 5.5))
                err = Exception("EnrichmentTimeoutError: maxmind-geoip2 did not respond within 3s SLA")
                entry_span.record_exception(err)
                entry_span.set_status(StatusCode.ERROR, str(err))
                # Non-fatal: pipeline continues without enrichment
                exit_span.set_attribute("enrichment.degraded", True)
                enr_timeouts.add(1, attributes={"enrichment.provider": "maxmind-geoip2"})
                enrichment.logger.warning(
                    f"enrichment timeout: proceeding without geo data",
                    extra={"event.batch_id": batch_id, "event.type": event_type,
                           "enrichment.timeout_ms": 3000, "enrichment.degraded": True}
                )
                return 0, "unknown", "unknown", inject_traceparent(entry_span)

            time.sleep(random.uniform(0.04, 0.12))

            geo_country  = random.choice(GEO_COUNTRIES)
            user_segment = random.choice(USER_SEGMENTS)
            enriched_count = len(records)

            dur_ms = (time.time() - t0) * 1000
            enr_enriched.add(enriched_count, attributes={"event.type": event_type})
            enr_latency.record(dur_ms, attributes={"enrichment.providers": "maxmind-geoip2"})

            entry_span.set_attribute("enrichment.geo_country",    geo_country)
            entry_span.set_attribute("enrichment.user_segment",   user_segment)
            entry_span.set_attribute("enrichment.records_enriched", enriched_count)
            entry_span.set_attribute("enrichment.geo_hit_rate",   0.97)

            enrichment.logger.info(
                f"enrichment complete: {enriched_count} records enriched",
                extra={"event.batch_id": batch_id, "event.type": event_type,
                       "enrichment.geo_country": geo_country,
                       "enrichment.user_segment": user_segment,
                       "enrichment.records_enriched": enriched_count}
            )
            return enriched_count, geo_country, user_segment, inject_traceparent(entry_span)


def svc_storage_writer(batch_id: str, event_type: str, records_count: int,
                         bytes_count: int, parent_tp: str,
                         force_backpressure: bool = False) -> tuple:
    """Write records to S3 / data warehouse."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()
    s3_path = STORAGE_PATHS.get(event_type, "s3://data-lake/events/misc/")
    partition = f"year={time.strftime('%Y')}/month={time.strftime('%m')}/day={time.strftime('%d')}"

    with ingest.tracer.start_as_current_span(
        "http.client.storage_writer", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "PUT", "net.peer.name": "storage-writer",
                    "http.url": "http://storage-writer/api/v1/write",
                    "event.batch_id": batch_id, "storage.path": s3_path,
                    "records.count": records_count}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with storage.tracer.start_as_current_span(
            "storage.write_batch", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "PUT", "http.route": "/api/v1/write",
                        "event.batch_id": batch_id, "event.type": event_type,
                        "storage.backend": "s3+parquet", "storage.path": s3_path,
                        "storage.partition": partition, "storage.compression": "snappy",
                        "records.count": records_count}
        ) as entry_span:
            if force_backpressure:
                # Simulate backpressure — retry after backoff
                for attempt in range(3):
                    backoff = 2 ** attempt * 0.5
                    storage.logger.warning(
                        f"storage backpressure: write buffer full, retry {attempt+1}/3 in {backoff}s",
                        extra={"event.batch_id": batch_id, "storage.retry_attempt": attempt + 1,
                               "storage.backoff_seconds": backoff}
                    )
                    sto_retries.add(1, attributes={"event.type": event_type})
                    time.sleep(backoff)
                    if attempt >= 1:  # succeed on 2nd retry
                        break
                entry_span.set_attribute("storage.retries", 2)

            time.sleep(random.uniform(0.05, 0.15))

            file_key = f"{s3_path}{partition}/batch-{batch_id}.parquet"
            dur_ms   = (time.time() - t0) * 1000

            entry_span.set_attribute("storage.file_key",       file_key)
            entry_span.set_attribute("storage.bytes_written",  bytes_count)
            entry_span.set_attribute("storage.records_written", records_count)
            entry_span.set_attribute("storage.format",         "parquet")

            sto_written.add(records_count, attributes={"event.type": event_type})
            sto_bytes.record(bytes_count, attributes={"storage.backend": "s3+parquet"})

            storage.logger.info(
                f"batch written to storage: {file_key}",
                extra={"event.batch_id": batch_id, "storage.file_key": file_key,
                       "storage.bytes_written": bytes_count,
                       "storage.records_written": records_count,
                       "storage.duration_ms": round(dur_ms, 2)}
            )
            return file_key, inject_traceparent(entry_span)


def svc_search_indexer(batch_id: str, event_type: str, records_count: int,
                         geo_country: str, user_segment: str,
                         parent_tp: str) -> None:
    """Index documents into Elasticsearch."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()
    index_name = f"events-{event_type}-{time.strftime('%Y.%m.%d')}"

    with ingest.tracer.start_as_current_span(
        "http.client.search_indexer", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "search-indexer",
                    "http.url": "http://search-indexer/api/v1/index",
                    "event.batch_id": batch_id, "index.name": index_name}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with indexer.tracer.start_as_current_span(
            "index.bulk_insert", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v1/index",
                        "event.batch_id": batch_id, "event.type": event_type,
                        "index.name": index_name, "index.backend": "elasticsearch-8",
                        "index.shards": 5, "index.replicas": 1,
                        "records.count": records_count,
                        "enrichment.geo_country": geo_country,
                        "enrichment.user_segment": user_segment}
        ) as entry_span:
            time.sleep(random.uniform(0.03, 0.10))

            dur_ms = (time.time() - t0) * 1000
            entry_span.set_attribute("index.docs_indexed",  records_count)
            entry_span.set_attribute("index.took_ms",       round(dur_ms, 2))
            entry_span.set_attribute("index.errors",        0)

            idx_docs.add(records_count, attributes={"event.type": event_type,
                                                     "index.name": index_name})
            idx_latency.record(dur_ms, attributes={"index.backend": "elasticsearch-8"})

            indexer.logger.info(
                f"indexed {records_count} docs into {index_name}",
                extra={"event.batch_id": batch_id, "index.name": index_name,
                       "index.docs_indexed": records_count,
                       "enrichment.geo_country": geo_country,
                       "index.took_ms": round(dur_ms, 2)}
            )


# ── Main scenario runner ───────────────────────────────────────────────────────

def run_pipeline_scenario(scenario: str, event_type: str, source: str, batch_size: int):
    """Run a full pipeline ingestion scenario."""
    t_start  = time.time()

    force_corrupt      = scenario == "schema_failure"
    force_duplicate    = scenario == "duplicate"
    force_malformed    = scenario == "transform_error"
    force_enr_timeout  = scenario == "enrichment_timeout"
    force_backpressure = scenario == "storage_backpressure"

    batch = make_batch(event_type, source, batch_size,
                       corrupt=force_corrupt, duplicate=force_duplicate)
    batch_id = batch["batch_id"]

    print(f"\n  [{scenario}] batch={batch_id} type={event_type} "
          f"source={source} records={batch_size}")

    with ingest.tracer.start_as_current_span(
        "ingest.receive_batch", kind=SpanKind.SERVER,
        attributes={"http.method": "POST", "http.route": "/api/v1/ingest",
                    "event.batch_id": batch_id, "event.type": event_type,
                    "event.source": source, "records.count": batch_size,
                    "pipeline.version": "v4.2.0", "scenario": scenario}
    ) as root_span:
        tp_root = inject_traceparent(root_span)
        ing_events.add(batch_size, attributes={"event.type": event_type, "event.source": source})
        ing_batch_size.record(batch_size, attributes={"event.type": event_type})

        ingest.logger.info(
            f"batch received: {batch_id} ({batch_size} records)",
            extra={"event.batch_id": batch_id, "event.type": event_type,
                   "event.source": source, "records.count": batch_size}
        )

        try:
            # Stage 1: schema validation
            valid_count, tp = svc_schema_validator(
                batch_id, event_type, batch["records"], tp_root,
                corrupt=force_corrupt)

            # Stage 2: deduplication
            unique_count, tp = svc_dedup(
                batch_id, event_type, batch["records"], tp_root,
                force_duplicate=force_duplicate)

            # Stage 3: transform
            transformed, bytes_out, tp = svc_transform(
                batch_id, event_type, source, batch["records"], tp_root,
                force_malformed=force_malformed)

            # Stage 4: enrichment (non-fatal if timeout)
            enr_result = svc_enrichment(
                batch_id, event_type, batch["records"], source, tp_root,
                force_timeout=force_enr_timeout)
            enr_count, geo_country, user_segment, tp = enr_result

            if geo_country == "unknown":
                root_span.set_attribute("pipeline.enrichment_degraded", True)
                ingest.logger.warning(
                    f"pipeline degraded: enrichment skipped for batch {batch_id}",
                    extra={"event.batch_id": batch_id, "pipeline.stage": "enrichment",
                           "pipeline.degraded": True}
                )

            # Stage 5: storage write
            file_key, tp = svc_storage_writer(
                batch_id, event_type, transformed, bytes_out, tp_root,
                force_backpressure=force_backpressure)

            # Stage 6: search index
            svc_search_indexer(
                batch_id, event_type, transformed, geo_country, user_segment, tp_root)

            dur_ms = (time.time() - t_start) * 1000
            root_span.set_attribute("pipeline.stage",        "complete")
            root_span.set_attribute("pipeline.records_in",   batch_size)
            root_span.set_attribute("pipeline.records_out",  transformed)
            root_span.set_attribute("pipeline.latency_ms",   round(dur_ms, 2))
            root_span.set_attribute("enrichment.geo_country", geo_country)
            root_span.set_attribute("pipeline.file_key",     file_key)

            ing_latency.record(dur_ms, attributes={"result": "success", "event.type": event_type})
            ingest.logger.info(
                f"pipeline complete: {batch_id} {transformed}/{batch_size} records",
                extra={"event.batch_id": batch_id, "event.type": event_type,
                       "pipeline.records_in": batch_size, "pipeline.records_out": transformed,
                       "pipeline.latency_ms": round(dur_ms, 2), "storage.file_key": file_key,
                       "enrichment.geo_country": geo_country}
            )

            tag = "⚠️" if geo_country == "unknown" else "✅"
            suffix = " (enrichment degraded)" if geo_country == "unknown" else ""
            print(f"    {tag} Pipeline complete{suffix}: {transformed}/{batch_size} records → {file_key}")
            return True

        except Exception as e:
            root_span.record_exception(e)
            root_span.set_status(StatusCode.ERROR, str(e))
            dur_ms = (time.time() - t_start) * 1000
            err_type = type(e).__name__
            ing_rejected.add(batch_size, attributes={"event.type": event_type,
                                                      "error.type": err_type})
            ing_latency.record(dur_ms, attributes={"result": "error", "event.type": event_type})
            ingest.logger.error(
                f"pipeline failed: {err_type}: {e}",
                extra={"event.batch_id": batch_id, "event.type": event_type,
                       "error.type": err_type, "pipeline.failed_at": scenario,
                       "pipeline.latency_ms": round(dur_ms, 2)}
            )

            if "Schema" in err_type or "Missing" in str(e):
                print(f"    ❌ Schema failure: {e}")
            elif "Duplicate" in err_type:
                print(f"    🚫 Duplicate rejected: {e}")
            elif "Unicode" in str(e) or "Transform" in err_type:
                print(f"    ❌ Transform error: {e}")
            elif "Timeout" in str(e):
                print(f"    ⚠️  Service timeout: {e}")
            else:
                print(f"    ❌ Error: {e}")
            return False


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{'='*70}")
    print("  Real-Time Data Ingestion Pipeline — Distributed Tracing Demo")
    print("  Services: ingest-api → schema-validator → dedup-service")
    print("            → transform-worker → enrichment-service")
    print("            → storage-writer → search-indexer")
    print(f"{'='*70}")

    # 25 scenarios
    scenario_pool = (
        ["clean_ingest"] * 15 +
        ["schema_failure"] * 4 +
        ["duplicate"] * 2 +
        ["transform_error"] * 2 +
        ["enrichment_timeout"] * 1 +
        ["storage_backpressure"] * 1
    )
    random.shuffle(scenario_pool)

    stats = {"success": 0, "schema_failure": 0, "duplicate": 0,
             "transform_error": 0, "enrichment_timeout": 0,
             "storage_backpressure": 0, "total": 0}

    for i, scenario in enumerate(scenario_pool):
        event_type = random.choice(EVENT_TYPES)
        source     = random.choice(EVENT_SOURCES)
        batch_size = random.randint(10, 500)

        print(f"\n{'─'*70}")
        print(f"  Scenario {i+1:02d}/25  [{scenario}]")
        result = run_pipeline_scenario(scenario, event_type, source, batch_size)
        stats["total"] += 1
        if result:
            if scenario == "enrichment_timeout":
                stats["enrichment_timeout"] += 1
            elif scenario == "storage_backpressure":
                stats["storage_backpressure"] += 1
            else:
                stats["success"] += 1
        elif scenario in stats:
            stats[scenario] += 1

        time.sleep(random.uniform(0.1, 0.3))

    print(f"\n{'='*70}")
    print("  Flushing all telemetry providers...")
    for svc in [ingest, schema, dedup, transform, enrichment, storage, indexer]:
        svc.flush()

    print(f"\n  Results: {stats['total']} scenarios")
    print(f"    ✅ Success:              {stats['success']}")
    print(f"    ❌ Schema failures:      {stats['schema_failure']}")
    print(f"    🚫 Duplicates:           {stats['duplicate']}")
    print(f"    ❌ Transform errors:     {stats['transform_error']}")
    print(f"    ⚠️  Enrichment timeouts: {stats['enrichment_timeout']}")
    print(f"    ⚠️  Storage backpressure:{stats['storage_backpressure']}")

    print(f"\n  Kibana:")
    print(f"    Service Map → Observability → APM → Service Map")
    print(f"    Filter: ingest-api (7 connected nodes expected)")
    print(f"\n  ES|QL query:")
    print(f'    FROM traces-apm*,logs-*')
    print(f'    | WHERE service.name IN ("ingest-api","schema-validator","dedup-service",')
    print(f'        "transform-worker","enrichment-service","storage-writer","search-indexer")')
    print(f'    | SORT @timestamp DESC | LIMIT 100')
    print(f"{'='*70}\n")
