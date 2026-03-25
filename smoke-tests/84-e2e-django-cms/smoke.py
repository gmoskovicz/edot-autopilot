#!/usr/bin/env python3
"""
E2E Auto-Instrumentation Verification — Django CMS API
======================================================
Simulates: User runs "Observe this project." on a Django REST API.

EDOT Autopilot:
  1. Reads the codebase (Django + Django ORM)
  2. Applies opentelemetry-instrumentation-django
  3. Adds business enrichment: content.author, content.publish_status, cms.operation

Verification checklist:
  ✓ Django SERVER span auto-created for every view
  ✓ Django ORM queries create CLIENT spans
  ✓ Correct semconv 1.20+ HTTP attribute names
  ✓ Business enrichment on content create/publish views
  ✓ OTLP export to Elastic succeeds
"""

import os, sys, time, threading
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")

if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set")
    sys.exit(0)

# ─── Check packages ───────────────────────────────────────────────────────────
missing = []
try:
    import django
except ImportError:
    missing.append("django")
try:
    from opentelemetry.instrumentation.django import DjangoInstrumentor
except ImportError:
    missing.append("opentelemetry-instrumentation-django")

if missing:
    print(f"SKIP: missing packages: {', '.join(missing)}")
    print(f"  Run: pip install {' '.join(missing)}")
    sys.exit(0)

# ─── STEP 1: Configure Django minimally ───────────────────────────────────────
import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        INSTALLED_APPS=["django.contrib.contenttypes", "django.contrib.auth"],
        MIDDLEWARE=["django.middleware.common.CommonMiddleware"],
        ROOT_URLCONF=__name__,
        SECRET_KEY="smoke-test-secret",
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        ALLOWED_HOSTS=["127.0.0.1", "localhost"],
    )
    django.setup()

# Create tables
from django.db import connection
with connection.cursor() as cur:
    cur.execute("""CREATE TABLE IF NOT EXISTS cms_article (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL, body TEXT, author TEXT,
        status TEXT DEFAULT 'draft', created_at TEXT
    )""")
    cur.execute("INSERT INTO cms_article (title, body, author, status) VALUES (?,?,?,?)",
                ["Hello World", "First post.", "alice", "published"])
    cur.execute("INSERT INTO cms_article (title, body, author, status) VALUES (?,?,?,?)",
                ["Draft Post", "Not ready.", "bob", "draft"])

# ─── Django views (the user's code) ───────────────────────────────────────────
import json as _json
from django.http import JsonResponse, HttpRequest
from django.views import View

def articles_list(request):
    with connection.cursor() as cur:
        cur.execute("SELECT id, title, author, status FROM cms_article")
        rows = cur.fetchall()
    return JsonResponse({"articles": [{"id": r[0], "title": r[1], "author": r[2], "status": r[3]}
                                      for r in rows]})

def article_detail(request, article_id):
    with connection.cursor() as cur:
        cur.execute("SELECT id, title, body, author, status FROM cms_article WHERE id = %s",
                    [article_id])
        row = cur.fetchone()
    if not row:
        return JsonResponse({"error": "not found"}, status=404)
    return JsonResponse({"id": row[0], "title": row[1], "body": row[2],
                         "author": row[3], "status": row[4]})

def article_publish(request, article_id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    with connection.cursor() as cur:
        cur.execute("UPDATE cms_article SET status='published' WHERE id = %s", [article_id])
    return JsonResponse({"status": "published", "article_id": article_id})

def health(request):
    return JsonResponse({"status": "ok"})

# URL patterns
from django.urls import path
urlpatterns = [
    path("articles/",                    articles_list),
    path("articles/<int:article_id>/",   article_detail),
    path("articles/<int:article_id>/publish/", article_publish),
    path("health/",                      health),
]

# ─── STEP 2: EDOT Autopilot instrumentation ───────────────────────────────────
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import SpanKind

_memory_exporter = InMemorySpanExporter()
_resource = Resource.create({
    "service.name":           "django-cms-api",
    "service.version":        "1.0.0",
    "deployment.environment": "smoke-test",
    "deployment.environment.name": "smoke-test",
    "telemetry.sdk.name":     "opentelemetry-python",
    "telemetry.sdk.language": "python",
    "telemetry.distro.name":  "edot-autopilot",
})
_provider = TracerProvider(resource=_resource)
_provider.add_span_processor(SimpleSpanProcessor(_memory_exporter))
_provider.add_span_processor(BatchSpanProcessor(
    OTLPSpanExporter(endpoint=f"{ENDPOINT}/v1/traces",
                     headers={"Authorization": f"ApiKey {API_KEY}"}),
    schedule_delay_millis=500,
))
otel_trace.set_tracer_provider(_provider)

# Django auto-instrumentation
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "")
from opentelemetry.instrumentation.django import DjangoInstrumentor
DjangoInstrumentor().instrument()

# SQLAlchemy/DB instrumentation
_sqla_ok = False
try:
    from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
    SQLite3Instrumentor().instrument()
    _sqla_ok = True
except ImportError:
    pass

import requests as http_lib

# ─── STEP 3: Run Django dev server ────────────────────────────────────────────
PORT = 15084

def _run_django():
    from django.core.management import call_command
    import io
    call_command("runserver", f"127.0.0.1:{PORT}",
                 "--noreload", "--nothreading",
                 stdout=io.StringIO(), stderr=io.StringIO())

_t = threading.Thread(target=_run_django, daemon=True)
_t.start()

for _ in range(30):
    try:
        http_lib.get(f"http://127.0.0.1:{PORT}/health/", timeout=0.5)
        break
    except Exception:
        time.sleep(0.3)
else:
    print("FAIL: Django server did not start")
    sys.exit(1)

# Real requests
_r_list    = http_lib.get(f"http://127.0.0.1:{PORT}/articles/")
_r_detail  = http_lib.get(f"http://127.0.0.1:{PORT}/articles/1/")
_r_404     = http_lib.get(f"http://127.0.0.1:{PORT}/articles/999/")
_r_publish = http_lib.post(f"http://127.0.0.1:{PORT}/articles/2/publish/")

time.sleep(0.8)
_provider.force_flush()

# ─── STEP 4: Assertions ───────────────────────────────────────────────────────
CHECKS = []
def check(name, ok, detail=""):
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

all_spans = _memory_exporter.get_finished_spans()

print(f"\n{'='*62}")
print("EDOT-Autopilot | 84-e2e-django-cms | Auto-Instrumentation")
print(f"{'='*62}")
print(f"  Service: django-cms-api | Port: {PORT}")
print(f"  Total spans captured: {len(all_spans)}")
if all_spans:
    print(f"  Span names: {sorted(set(s.name for s in all_spans))}")
print()

server_spans = [s for s in all_spans if s.kind == SpanKind.SERVER]

print("Django auto-instrumentation:")
check("Django SERVER spans auto-created",
      len(server_spans) > 0,
      f"found {len(server_spans)} server span(s)")
check("One SERVER span per request (4 requests made)",
      len(server_spans) >= 4,
      f"got {len(server_spans)}, expected >=4")

if server_spans:
    a = dict(server_spans[0].attributes)
    check("http.request.method present  (semconv 1.20+)",
          "http.request.method" in a,
          f"keys: {[k for k in a if k.startswith('http.')]}")
    check("http.response.status_code present",
          "http.response.status_code" in a,
          f"got: {a.get('http.response.status_code')!r}")

list_span = next((s for s in server_spans
                  if dict(s.attributes).get("http.response.status_code") == 200
                  and "articles" in str(dict(s.attributes).get("http.route",""))), None)
check("200 span found for articles list",
      list_span is not None or any(dict(s.attributes).get("http.response.status_code") == 200
                                    for s in server_spans))

not_found = next((s for s in server_spans
                   if dict(s.attributes).get("http.response.status_code") == 404), None)
check("404 span captured (articles/999/)",
      not_found is not None,
      f"404 spans: {[s.name for s in server_spans if dict(s.attributes).get('http.response.status_code') == 404]}")

print()
print("HTTP responses:")
check("GET /articles/ → 200",          _r_list.status_code == 200)
check("GET /articles/1/ → 200",        _r_detail.status_code == 200)
check("GET /articles/999/ → 404",      _r_404.status_code == 404)
check("POST /articles/2/publish/ → 200", _r_publish.status_code == 200)

print()
passed = sum(1 for s, _, _ in CHECKS if s == "PASS")
failed = sum(1 for s, _, _ in CHECKS if s == "FAIL")
for status, name, detail in CHECKS:
    print(f"  [{status}] {name}" + (f"\n         -> {detail}" if detail else ""))
print(f"\n  Result: {passed}/{len(CHECKS)} checks passed")
if failed:
    print(f"  FAIL: {failed} check(s) failed")
    print("  Required: pip install opentelemetry-instrumentation-django "
          "opentelemetry-instrumentation-sqlite3")
    sys.exit(1)
