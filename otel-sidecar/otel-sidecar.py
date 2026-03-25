#!/usr/bin/env python3
"""
OTEL Sidecar — universal telemetry bridge for runtimes without OTel SDK support.

Any process that can make an HTTP POST can now emit traces, logs, and metrics
to Elastic APM. COBOL, Perl, Bash, PowerShell, SAP ABAP, IBM RPG, Flutter — anything.

API:
  POST /
    {"action": "event",             "name": "...", "attributes": {}}
    {"action": "start_span",        "name": "...", "attributes": {}, "span_id": "optional", "traceparent": "optional"}
    {"action": "end_span",          "span_id": "...", "attributes": {}, "error": "optional message"}
    {"action": "log",               "body": "...", "severity": "INFO", "attributes": {}, "traceparent": "optional"}
    {"action": "metric_counter",    "name": "...", "value": 1, "attributes": {}, "traceparent": "optional"}
    {"action": "metric_gauge",      "name": "...", "value": 42.0, "attributes": {}}
    {"action": "metric_histogram",  "name": "...", "value": 123.4, "attributes": {}}
    {"action": "health"}  → {"ok": true, "spans_active": N}

Environment variables:
  OTEL_SERVICE_NAME           (required)
  ELASTIC_OTLP_ENDPOINT       (required) — e.g. https://xxx.ingest.us-central1.gcp.elastic.cloud:443
  ELASTIC_API_KEY             (required)
  OTEL_DEPLOYMENT_ENVIRONMENT (default: production)
  SERVICE_VERSION             (default: unknown)
  SIDECAR_PORT                (default: 9411)
  SIDECAR_HOST                (default: 127.0.0.1)
"""

import os
import json
import uuid
import logging
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.context import attach, detach

from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [sidecar] %(message)s")
log = logging.getLogger("otel-sidecar")

# ── Bootstrap OTel providers ──────────────────────────────────────────────────

resource = Resource.create({
    "service.name":           os.environ["OTEL_SERVICE_NAME"],
    "service.version":        os.environ.get("SERVICE_VERSION", "unknown"),
    "deployment.environment": os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "production"),
})

otlp_endpoint = os.environ["ELASTIC_OTLP_ENDPOINT"].rstrip("/")
api_key = os.environ["ELASTIC_API_KEY"]
headers = {"Authorization": f"ApiKey {api_key}"}

# Traces
trace_exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces", headers=headers)
trace_provider = TracerProvider(resource=resource)
trace_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
trace.set_tracer_provider(trace_provider)
tracer = trace.get_tracer("otel-sidecar")

# Logs
log_exporter = OTLPLogExporter(endpoint=f"{otlp_endpoint}/v1/logs", headers=headers)
log_provider = LoggerProvider(resource=resource)
log_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
# Bridge stdlib logger through to OTLP — attach to a dedicated sidecar-events logger
_otel_log_handler = LoggingHandler(logger_provider=log_provider)
_otel_logger = logging.getLogger("sidecar.events")
_otel_logger.setLevel(logging.DEBUG)
_otel_logger.addHandler(_otel_log_handler)
_otel_logger.propagate = False

# Metrics
metric_exporter = OTLPMetricExporter(endpoint=f"{otlp_endpoint}/v1/metrics", headers=headers)
metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=10_000)
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
metrics.set_meter_provider(meter_provider)
meter = metrics.get_meter("otel-sidecar")

# Instrument registry — prevents duplicate creation errors
_instruments: dict = {}

# span_id → (span_object, otel_context_token)
_spans: dict = {}

propagator = TraceContextTextMapPropagator()

_SEVERITY_MAP = {
    "TRACE": logging.DEBUG - 4,
    "DEBUG": logging.DEBUG,
    "INFO":  logging.INFO,
    "WARN":  logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "FATAL": logging.CRITICAL,
}


def _get_or_create_counter(name: str):
    key = ("counter", name)
    if key not in _instruments:
        _instruments[key] = meter.create_counter(name)
    return _instruments[key]


def _get_or_create_gauge(name: str):
    key = ("gauge", name)
    if key not in _instruments:
        _instruments[key] = meter.create_observable_gauge(name)
    return _instruments[key]


def _get_or_create_histogram(name: str):
    key = ("histogram", name)
    if key not in _instruments:
        _instruments[key] = meter.create_histogram(name)
    return _instruments[key]


# ── HTTP handler ──────────────────────────────────────────────────────────────

class SidecarHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as e:
            self._respond(400, {"ok": False, "error": f"invalid JSON: {e}"})
            return

        action = body.get("action", "event")

        if action == "health":
            self._respond(200, {"ok": True, "spans_active": len(_spans)})
            return

        if action == "start_span":
            span_id = body.get("span_id") or str(uuid.uuid4())
            ctx_token = None

            if tp := body.get("traceparent"):
                parent_ctx = propagator.extract({"traceparent": tp})
                ctx_token = attach(parent_ctx)

            span = tracer.start_span(
                body.get("name", "unnamed"),
                attributes=body.get("attributes", {}),
            )
            _spans[span_id] = (span, ctx_token)
            sc = span.get_span_context()
            traceparent = f"00-{sc.trace_id:032x}-{sc.span_id:016x}-01"
            log.info("start_span name=%s span_id=%s", body.get("name"), span_id)
            self._respond(200, {"ok": True, "span_id": span_id, "traceparent": traceparent})
            return

        if action == "end_span":
            span_id = body.get("span_id")
            entry = _spans.pop(span_id, None)
            if not entry:
                self._respond(404, {"ok": False, "error": f"span_id {span_id!r} not found"})
                return
            span, ctx_token = entry
            for k, v in body.get("attributes", {}).items():
                span.set_attribute(k, v)
            if err := body.get("error"):
                span.set_status(trace.StatusCode.ERROR, err)
            span.end()
            if ctx_token is not None:
                detach(ctx_token)
            log.info("end_span span_id=%s", span_id)
            self._respond(200, {"ok": True})
            return

        if action == "log":
            severity_name = body.get("severity", "INFO").upper()
            level = _SEVERITY_MAP.get(severity_name, logging.INFO)
            message = body.get("body", "")
            attrs = body.get("attributes", {})

            ctx_token = None
            if tp := body.get("traceparent"):
                parent_ctx = propagator.extract({"traceparent": tp})
                ctx_token = attach(parent_ctx)

            # Build extra dict for structured log fields
            extra = {k: v for k, v in attrs.items()}
            _otel_logger.log(level, message, extra=extra)

            if ctx_token is not None:
                detach(ctx_token)

            log.info("log severity=%s body=%s", severity_name, message[:60])
            self._respond(200, {"ok": True})
            return

        if action == "metric_counter":
            name = body.get("name", "sidecar.events")
            value = int(body.get("value", 1))
            attrs = body.get("attributes", {})
            counter = _get_or_create_counter(name)
            counter.add(value, attributes=attrs)
            log.info("metric_counter name=%s value=%s", name, value)
            self._respond(200, {"ok": True})
            return

        if action == "metric_histogram":
            name = body.get("name", "sidecar.duration_ms")
            value = float(body.get("value", 0))
            attrs = body.get("attributes", {})
            histogram = _get_or_create_histogram(name)
            histogram.record(value, attributes=attrs)
            log.info("metric_histogram name=%s value=%s", name, value)
            self._respond(200, {"ok": True})
            return

        if action == "metric_gauge":
            # Gauges via up-down counter (observable gauges need callbacks)
            # Use histogram with a single observation as a gauge proxy
            name = body.get("name", "sidecar.gauge")
            value = float(body.get("value", 0))
            attrs = body.get("attributes", {})
            key = ("updown", name)
            if key not in _instruments:
                _instruments[key] = meter.create_up_down_counter(name)
            # Emit as up-down counter difference — reset not possible in OTel,
            # so we just record the value as an increment for smoke purposes
            _instruments[key].add(value, attributes=attrs)
            log.info("metric_gauge name=%s value=%s", name, value)
            self._respond(200, {"ok": True})
            return

        # Default: fire-and-forget event span
        attrs = body.get("attributes", {})
        name  = body.get("name", "unnamed.event")
        with tracer.start_as_current_span(name, attributes=attrs) as span:
            if err := body.get("error"):
                span.set_status(trace.StatusCode.ERROR, err)
        log.info("event name=%s", name)
        self._respond(200, {"ok": True})

    def _respond(self, status: int, payload: dict):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass  # suppress default access log — we use our own


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    host = os.environ.get("SIDECAR_HOST", "127.0.0.1")
    port = int(os.environ.get("SIDECAR_PORT", 9411))
    log.info("OTEL Sidecar starting on %s:%d (traces + logs + metrics)", host, port)
    log.info("Service: %s  Endpoint: %s", os.environ["OTEL_SERVICE_NAME"], otlp_endpoint)
    HTTPServer((host, port), SidecarHandler).serve_forever()
