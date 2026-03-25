#!/usr/bin/env python3
"""
OTEL Sidecar — universal telemetry bridge for runtimes without OTel SDK support.

Any process that can make an HTTP POST can now emit spans to Elastic APM.
COBOL, Perl, Bash, PowerShell, SAP ABAP, IBM RPG, Flutter — anything.

API:
  POST /
    {"action": "event",      "name": "...", "attributes": {}}
    {"action": "start_span", "name": "...", "attributes": {}, "span_id": "optional", "traceparent": "optional"}
    {"action": "end_span",   "span_id": "...", "attributes": {}, "error": "optional message"}
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
from http.server import HTTPServer, BaseHTTPRequestHandler

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.context import attach, detach

logging.basicConfig(level=logging.INFO, format="%(asctime)s [sidecar] %(message)s")
log = logging.getLogger("otel-sidecar")

# ── Bootstrap OTel provider ───────────────────────────────────────────────────

resource = Resource.create({
    "service.name":           os.environ["OTEL_SERVICE_NAME"],
    "service.version":        os.environ.get("SERVICE_VERSION", "unknown"),
    "deployment.environment": os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "production"),
})

otlp_endpoint = os.environ["ELASTIC_OTLP_ENDPOINT"].rstrip("/")
api_key = os.environ["ELASTIC_API_KEY"]

exporter = OTLPSpanExporter(
    endpoint=f"{otlp_endpoint}/v1/traces",
    headers={"Authorization": f"ApiKey {api_key}"},
)

provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("otel-sidecar")

# span_id → (span_object, otel_context_token)
_spans: dict = {}

propagator = TraceContextTextMapPropagator()

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

            # Accept W3C traceparent for distributed trace continuation
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
    log.info("OTEL Sidecar starting on %s:%d", host, port)
    log.info("Service: %s  Endpoint: %s", os.environ["OTEL_SERVICE_NAME"], otlp_endpoint)
    HTTPServer((host, port), SidecarHandler).serve_forever()
