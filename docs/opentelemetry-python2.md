# OpenTelemetry for Python 2.7 — Complete Guide

> How to instrument Python 2.7 applications that cannot be upgraded to Python 3 — and get their traces into Elastic APM.

## The problem

Python 2.7 reached official end-of-life on January 1, 2020. And yet a meaningful number of applications — particularly in quantitative finance, scientific computing, and legacy SaaS — still run on it. The reasons are always the same:

- The application uses a C extension or Fortran library with no Python 3 build
- It relies on a numeric library (NumPy fork, proprietary quant library) frozen at a Python 2 ABI
- The codebase is enormous and the upgrade project was scoped, scheduled, deferred, and never completed
- The application "works" and the business risk of touching it outweighs the maintenance burden

The modern OpenTelemetry Python SDK (`opentelemetry-sdk`) requires Python 3.7+. There is no official support for Python 2. The Elastic EDOT Python distribution inherits this requirement.

This means Python 2.7 applications have no path to auto-instrumentation — not through the EDOT SDK, not through vanilla OTel, not through any major APM vendor's agent.

The result: production Python 2.7 code that processes real business transactions — risk calculations, options pricing, genomic data pipelines — is completely invisible to your observability stack.

## The solution

There are two approaches, depending on your situation:

**Approach 1: Sidecar pattern (always works)**
Use the EDOT Autopilot telemetry sidecar. Your Python 2.7 code makes HTTP requests to the sidecar using `urllib2` (built into Python 2 standard library). The sidecar is Python 3 and handles all OTLP communication.

**Approach 2: Direct SDK (if a compatible build is available)**
An early version of `opentelemetry-sdk` (0.14b0 through 0.16b0) had partial Python 2.7 compatibility. This path is fragile and not recommended for new setups, but documented here for completeness.

For most Python 2.7 deployments, **Approach 1 is the right choice**: it requires no changes to your Python 2 dependencies, works regardless of which libraries your code uses, and gives you the same Elastic APM output.

## Step-by-step setup

### Step 1: Deploy the sidecar (Python 3 required on the same host)

Python 3 and the sidecar only need to be installed on the host — they do not need to be imported by your Python 2 application.

```bash
# On the same host as your Python 2 app
pip3 install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http

git clone https://github.com/gmoskovicz/edot-autopilot /opt/edot-autopilot
```

Set environment variables and start:

```bash
export OTEL_SERVICE_NAME=python2-risk-engine
export ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io
export ELASTIC_API_KEY=<your-base64-encoded-id:key>
export OTEL_DEPLOYMENT_ENVIRONMENT=production

python3 /opt/edot-autopilot/otel-sidecar/otel-sidecar.py &
```

### Step 2: Verify from Python 2

```python
# test_sidecar.py — run with python2
import urllib2, json

payload = json.dumps({
    'action': 'event',
    'name': 'sidecar.test',
    'attributes': {'test': 'true'}
})
req = urllib2.Request(
    'http://127.0.0.1:9411',
    data=payload,
    headers={'Content-Type': 'application/json'}
)
response = urllib2.urlopen(req, timeout=2)
print "Sidecar OK:", response.read()
```

### Step 3: Add the telemetry helper to your Python 2 code

Copy the helper functions into a shared module (e.g., `telemetry.py`) and import it wherever you need instrumentation.

### Step 4: Instrument critical business operations

Focus on the operations that matter most: pricing calculations, risk aggregations, order processing, data pipeline phases. Add instrumentation calls immediately before and after each.

## Code example

### Approach 1: Sidecar pattern (recommended)

#### Shared module: `telemetry.py` (Python 2.7)

```python
# telemetry.py — compatible with Python 2.7
# Provides otel_event(), otel_start_span(), otel_end_span()

import urllib2
import json
import uuid
import logging

SIDECAR_URL = 'http://127.0.0.1:9411'
_log = logging.getLogger('telemetry')


def _post(payload):
    """Fire-and-forget POST to the sidecar. Never raises."""
    try:
        data = json.dumps(payload)
        req = urllib2.Request(
            SIDECAR_URL,
            data=data,
            headers={'Content-Type': 'application/json'}
        )
        urllib2.urlopen(req, timeout=1).read()
    except Exception as e:
        _log.debug('Telemetry sidecar unreachable: %s', e)


def otel_event(name, attributes=None, error=None):
    """Emit a point-in-time event span."""
    payload = {'action': 'event', 'name': name, 'attributes': attributes or {}}
    if error:
        payload['error'] = str(error)
    _post(payload)


def otel_start_span(name, attributes=None):
    """Start a span and return its span_id for later end_span call."""
    try:
        data = json.dumps({
            'action': 'start_span',
            'name': name,
            'attributes': attributes or {}
        })
        req = urllib2.Request(
            SIDECAR_URL,
            data=data,
            headers={'Content-Type': 'application/json'}
        )
        response = urllib2.urlopen(req, timeout=1).read()
        return json.loads(response).get('span_id')
    except Exception as e:
        _log.debug('otel_start_span failed: %s', e)
        return None


def otel_end_span(span_id, error=None, attributes=None):
    """End a previously started span."""
    if not span_id:
        return
    payload = {
        'action': 'end_span',
        'span_id': span_id,
        'attributes': attributes or {}
    }
    if error:
        payload['error'] = str(error)
    _post(payload)
```

#### Options pricing engine

```python
# pricer.py — Python 2.7 options pricing
from telemetry import otel_start_span, otel_end_span, otel_event
import time


def price_option(option_id, underlying, strike, expiry, vol, rate):
    """Price a single option using Black-Scholes."""
    span = otel_start_span('option.price', attributes={
        'option.id':         option_id,
        'option.underlying': underlying,
        'option.strike':     strike,
        'option.expiry':     expiry,
        'market.vol':        vol,
        'market.rate':       rate,
    })

    try:
        result = black_scholes(underlying, strike, expiry, vol, rate)

        otel_end_span(span, attributes={
            'option.price':        result.price,
            'option.delta':        result.delta,
            'option.gamma':        result.gamma,
            'option.vega':         result.vega,
            'pricing.model':       'black-scholes',
        })
        return result

    except Exception as e:
        otel_end_span(span, error=str(e), attributes={
            'option.id': option_id,
        })
        raise


def run_portfolio_pricing(portfolio_id, positions):
    """Price all positions in a portfolio."""
    span = otel_start_span('portfolio.pricing', attributes={
        'portfolio.id':       portfolio_id,
        'positions.count':    len(positions),
    })

    priced = 0
    failed = 0
    total_value = 0.0

    for position in positions:
        try:
            result = price_option(**position)
            priced += 1
            total_value += result.price * position.get('quantity', 1)
        except Exception as e:
            failed += 1
            otel_event('option.pricing.failed', attributes={
                'option.id':    position.get('option_id'),
                'portfolio.id': portfolio_id,
                'error':        str(e),
            })

    otel_end_span(span, attributes={
        'portfolio.id':      portfolio_id,
        'positions.priced':  priced,
        'positions.failed':  failed,
        'portfolio.value':   total_value,
        'pricing.status':    'complete' if failed == 0 else 'partial',
    })
```

#### Django 1.x / 1.11 request wrapping

```python
# middleware.py — Django 1.x compatible telemetry middleware
from telemetry import otel_start_span, otel_end_span
import time


class OtelMiddleware(object):
    """Wrap Django views with telemetry spans."""

    def process_request(self, request):
        span = otel_start_span(
            '{} {}'.format(request.method, request.path),
            attributes={
                'http.method': request.method,
                'http.path':   request.path,
                'user.id':     getattr(request, 'user', None) and
                               str(request.user.pk) or 'anonymous',
            }
        )
        request._otel_span = span

    def process_response(self, request, response):
        span = getattr(request, '_otel_span', None)
        if span:
            otel_end_span(span, attributes={
                'http.status_code': response.status_code,
            })
        return response

    def process_exception(self, request, exception):
        span = getattr(request, '_otel_span', None)
        if span:
            otel_end_span(span, error=str(exception), attributes={
                'error.type': type(exception).__name__,
            })
```

Add to `settings.py`:

```python
MIDDLEWARE_CLASSES = [
    'myapp.middleware.OtelMiddleware',
    # ... other middleware ...
]
```

### Approach 2: Direct SDK (fragile — use only if you cannot run sidecar)

This approach uses an old pre-release `opentelemetry-sdk` that had Python 2 compatibility. It is fragile, unsupported, and may conflict with other packages. Use Approach 1 instead unless you have a specific reason.

```python
# requirements-py2.txt
# WARNING: ancient pre-release, unsupported, use sidecar approach instead
opentelemetry-api==0.14b0
opentelemetry-sdk==0.14b0
opentelemetry-exporter-otlp==0.14b0
```

```python
# If you do use the old SDK directly (Python 2.7 with 0.14b0):
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchExportSpanProcessor
from opentelemetry.exporter.otlp.trace_exporter import OTLPSpanExporter

provider = TracerProvider()
provider.add_span_processor(BatchExportSpanProcessor(OTLPSpanExporter(
    endpoint="https://<deployment>.apm.<region>.cloud.es.io/v1/traces",
    headers={"Authorization": "ApiKey <key>"},
)))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("my.operation") as span:
    span.set_attribute("key", "value")
```

Again: this old SDK version is not maintained, has known bugs, and will not receive updates. The sidecar approach is more reliable.

## What you'll see in Elastic

After deploying the sidecar and adding instrumentation to your Python 2.7 code:

- **Named service** in Kibana APM (e.g., `python2-risk-engine`).
- **Business spans**: `portfolio.pricing`, `option.price`, each with the financial attributes you attached.
- **Duration tracking**: Pricing latency per portfolio, per underlying, over time. Useful for capacity planning and SLA reporting.
- **Failure analysis**: Options that fail to price appear in the Errors tab with error type and option ID.
- **Portfolio-level aggregations**: Query total portfolio value processed per hour, failure rates by underlying, etc.

Example ES|QL query to find slow portfolio pricing runs:

```esql
FROM traces-apm*
| WHERE service.name == "python2-risk-engine"
  AND span.name == "portfolio.pricing"
| EVAL duration_s = span.duration.us / 1000000
| WHERE duration_s > 30
| KEEP @timestamp, attributes.portfolio\.id, duration_s,
       attributes.positions\.count, attributes.positions\.failed
| SORT duration_s DESC
```

## Related

- [Telemetry Sidecar Pattern — full documentation](./telemetry-sidecar-pattern.md)
- [OpenTelemetry for Legacy Runtimes — overview](./opentelemetry-legacy-runtimes.md)
- [Business Span Enrichment](./business-span-enrichment.md)
- [otel-sidecar.py source](../otel-sidecar/otel-sidecar.py)
- [Elastic EDOT Python documentation](https://www.elastic.co/docs/reference/opentelemetry)

---

> Found this useful? [Star the repo](https://github.com/gmoskovicz/edot-autopilot) — it helps other Python 2 developers find this solution.
