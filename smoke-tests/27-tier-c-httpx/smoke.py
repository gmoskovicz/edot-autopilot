#!/usr/bin/env python3
"""
Smoke test: Tier C — httpx HTTP client (monkey-patched).

Patches httpx.Client.get and .post — existing call sites unchanged.
Business scenario: Currency exchange rate fetcher — call FX API,
parse rates, store to cache.

Run:
    cd smoke-tests && python3 27-tier-c-httpx/smoke.py
"""

import os, sys, uuid, time, random
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-c-httpx"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

http_counter = meter.create_counter("httpx.requests")
http_latency = meter.create_histogram("httpx.response_ms", unit="ms")
http_errors  = meter.create_counter("httpx.errors")

FX_RATES = {"USD/EUR": 0.92, "USD/GBP": 0.79, "USD/JPY": 149.8, "USD/BRL": 5.07, "EUR/USD": 1.09}


class _MockResponse:
    def __init__(self, status_code, json_data, url):
        self.status_code = status_code
        self._json       = json_data
        self.url         = url
        self.headers     = {"content-type": "application/json", "x-request-id": uuid.uuid4().hex}
    def json(self):
        return self._json
    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

class _MockHttpxClient:
    def get(self, url, **kwargs):
        time.sleep(random.uniform(0.02, 0.08))
        if random.random() < 0.05:
            raise Exception(f"httpx.ConnectTimeout connecting to {url}")
        pair = url.split("?")[0].split("/")[-1]
        rate = FX_RATES.get(pair, 1.0) * random.uniform(0.998, 1.002)
        return _MockResponse(200, {"pair": pair, "rate": round(rate, 4),
                                    "timestamp": int(time.time())}, url)

    def post(self, url, **kwargs):
        time.sleep(random.uniform(0.01, 0.04))
        return _MockResponse(201, {"stored": True, "key": kwargs.get("json", {}).get("key")}, url)

    def __enter__(self): return self
    def __exit__(self, *args): pass

class httpx:
    Client = _MockHttpxClient


_orig_get  = _MockHttpxClient.get
_orig_post = _MockHttpxClient.post

def _inst_get(self, url, **kwargs):
    t0 = time.time()
    with tracer.start_as_current_span("httpx.get", kind=SpanKind.CLIENT,
        attributes={"http.method": "GET", "http.url": url,
                    "http.client": "httpx"}) as span:
        try:
            resp = _orig_get(self, url, **kwargs)
            dur = (time.time() - t0) * 1000
            span.set_attribute("http.status_code",    resp.status_code)
            span.set_attribute("http.response_ms",    round(dur, 2))
            http_counter.add(1, attributes={"http.method": "GET", "http.status": str(resp.status_code)})
            http_latency.record(dur, attributes={"http.method": "GET"})
            return resp
        except Exception as e:
            span.set_status(StatusCode.ERROR, str(e))
            http_errors.add(1, attributes={"http.method": "GET"})
            logger.error("httpx GET failed", extra={"http.url": url, "error.message": str(e)})
            raise

def _inst_post(self, url, **kwargs):
    t0 = time.time()
    with tracer.start_as_current_span("httpx.post", kind=SpanKind.CLIENT,
        attributes={"http.method": "POST", "http.url": url, "http.client": "httpx"}) as span:
        resp = _orig_post(self, url, **kwargs)
        dur  = (time.time() - t0) * 1000
        span.set_attribute("http.status_code", resp.status_code)
        http_counter.add(1, attributes={"http.method": "POST", "http.status": str(resp.status_code)})
        http_latency.record(dur, attributes={"http.method": "POST"})
        return resp

_MockHttpxClient.get  = _inst_get
_MockHttpxClient.post = _inst_post


def fetch_fx_rate(base, quote):
    with httpx.Client() as client:
        resp = client.get(f"https://api.fx-provider.io/v2/rates/{base}/{quote}",
                          headers={"Authorization": "Bearer fx-api-key"})
        resp.raise_for_status()
        data = resp.json()
        client.post("https://api.fx-provider.io/v2/cache/store",
                    json={"key": f"fx:{base}:{quote}", "value": data["rate"], "ttl": 300})
        logger.info("FX rate fetched and cached",
                    extra={"fx.base_currency": base, "fx.quote_currency": quote,
                           "fx.rate": data["rate"], "fx.cache_ttl_sec": 300})
        return data["rate"]


print(f"\n[{SVC}] Fetching FX rates via patched httpx client...")
pairs = [("USD", "EUR"), ("USD", "GBP"), ("USD", "JPY"), ("EUR", "USD"), ("USD", "BRL")]
for base, quote in pairs:
    try:
        rate = fetch_fx_rate(base, quote)
        print(f"  ✅ {base}/{quote}  rate={rate:.4f}")
    except Exception as e:
        print(f"  🚫 {base}/{quote}  error={e}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
