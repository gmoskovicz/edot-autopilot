"""
Partial OTel Service — Flask API with incomplete instrumentation

Already has OTel. Run `Observe this project.` to improve it.

Problems to fix:
1. Uses deprecated semconv attribute names (http.method, http.status_code)
   instead of semconv 1.22+ names (http.request.method, http.response.status_code)
2. No business enrichment (no order.value_usd, customer.tier, etc.)
3. Error handling uses set_status(ERROR) without record_exception — stack traces
   are lost in Elastic APM
4. No force_flush on exit — spans silently dropped on shutdown

The agent must:
- NOT add a second TracerProvider (one already exists)
- Upgrade deprecated attribute names to semconv 1.22+
- Add business enrichment attributes
- Add record_exception to error paths
- Add atexit force_flush
"""

import os
import logging

from flask import Flask, jsonify, request

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.trace import Status, StatusCode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Existing TracerProvider — agent must NOT add a second one
provider = TracerProvider()
exporter = OTLPSpanExporter(
    endpoint=os.environ.get("ELASTIC_OTLP_ENDPOINT", "http://localhost:4318") + "/v1/traces",
    headers={"Authorization": f"ApiKey {os.environ.get('ELASTIC_API_KEY', '')}"},
)
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/orders", methods=["POST"])
def create_order():
    body = request.get_json(force=True)
    order_id = body.get("order_id", "ORD-001")
    customer_id = body.get("customer_id", "CUST-001")
    customer_tier = body.get("customer_tier", "standard")
    amount_usd = float(body.get("amount_usd", 0.0))

    if amount_usd <= 0:
        with tracer.start_as_current_span("order.validate") as span:
            # BUG: uses deprecated attribute name, no record_exception
            span.set_attribute("http.status_code", 400)  # deprecated
            span.set_status(Status(StatusCode.ERROR, "amount must be > 0"))
            # Missing: span.record_exception(exc)
        return jsonify({"error": "amount must be > 0"}), 400

    with tracer.start_as_current_span("order.process") as span:
        # BUG: uses deprecated attribute names
        span.set_attribute("http.method", request.method)  # deprecated
        span.set_attribute("http.status_code", 201)  # deprecated
        # Missing: order.value_usd, customer.tier, order.id

    logger.info("Order created", extra={
        "order_id": order_id,
        "customer_id": customer_id,
        "amount_usd": amount_usd,
    })

    return jsonify({
        "order_id": order_id,
        "status": "confirmed",
        "amount_usd": amount_usd,
        "customer_tier": customer_tier,
    }), 201


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
