# Tier B — Python 2.7 Manual Wrapping

EDOT's Python SDK requires Python 3.8+. Python 2.7 hit EOL in 2020 but still exists in enterprise environments (old Django 1.x apps, legacy CGI scripts, on-premise ERP integrations).

**Strategy:** If Python 3 is co-installed (very common), manually configure the OTel SDK. If not, fall back to the Tier D sidecar approach.

## The pattern

```python
def instrument_handler(handler_fn, route, method="GET"):
    """Tier B: wrap any legacy entry point with an OTel span."""
    def wrapped(*args, **kwargs):
        with tracer.start_as_current_span(f"{method} {route}", kind=SpanKind.SERVER) as span:
            try:
                result = handler_fn(*args, **kwargs)
                # Phase 3: add business attributes inside the handler
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, str(e))
                raise
    return wrapped

# Apply to each entry point — ONE LINE per handler
process_order = instrument_handler(_process_order_handler, "/api/orders", "POST")
```

## Run

```bash
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http

export ELASTIC_OTLP_ENDPOINT=https://YOUR-DEPLOYMENT.ingest.REGION.gcp.elastic.cloud:443
export ELASTIC_API_KEY=YOUR-BASE64-API-KEY
export OTEL_SERVICE_NAME=python27-tier-b

python app.py
```

## Verify in Elastic

Kibana → Observability → APM → Services → `python27-tier-b`
