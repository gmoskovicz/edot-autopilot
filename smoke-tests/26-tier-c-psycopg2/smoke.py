#!/usr/bin/env python3
"""
Smoke test: Tier C — psycopg2 PostgreSQL client (monkey-patched).

Patches cursor.execute and cursor.fetchall.
Business scenario: Analytics warehouse — daily sales rollup inserts
aggregate rows into a reporting schema.

Run:
    cd smoke-tests && python3 26-tier-c-psycopg2/smoke.py
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
from opentelemetry.trace import SpanKind

SVC = "smoke-tier-c-psycopg2"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

db_queries   = meter.create_counter("db.queries")
db_rows      = meter.create_histogram("db.rows_affected")
db_latency   = meter.create_histogram("db.query_ms", unit="ms")

_result_store = []


class _MockCursor:
    def __init__(self, conn):
        self._conn       = conn
        self.rowcount    = 0
        self._last_query = ""
        self._results    = []

    def execute(self, query, params=None):
        time.sleep(0.02)
        self._last_query = query.strip()[:80]
        self.rowcount    = random.randint(1, 50)
        self._results    = [(uuid.uuid4().hex[:8], random.uniform(100, 5000),
                             random.randint(1, 200)) for _ in range(min(5, self.rowcount))]

    def fetchall(self):
        return self._results

    def fetchone(self):
        return self._results[0] if self._results else None

    def __enter__(self): return self
    def __exit__(self, *args): pass

class _MockConnection:
    def __init__(self, dsn):
        self.dsn = dsn
    def cursor(self):
        return _MockCursor(self)
    def commit(self):
        pass
    def close(self):
        pass

class psycopg2:
    @staticmethod
    def connect(dsn=None, **kwargs):
        return _MockConnection(dsn or "host=analytics-db dbname=reporting")


_orig_execute  = _MockCursor.execute
_orig_fetchall = _MockCursor.fetchall

def _inst_execute(self, query, params=None):
    t0 = time.time()
    op = query.strip().split()[0].upper()
    with tracer.start_as_current_span(f"{op} reporting", kind=SpanKind.CLIENT,
        attributes={"db.system.name": "postgresql", "db.operation.name": op,
                    "db.query.text": query.strip()[:100],
                    "server.address": "analytics-db", "db.namespace": "reporting"}) as span:
        _orig_execute(self, query, params)
        dur = (time.time() - t0) * 1000
        span.set_attribute("db.response.returned_rows", self.rowcount)
        db_queries.add(1,   attributes={"db.operation.name": op})
        db_latency.record(dur,          attributes={"db.operation.name": op})
        db_rows.record(self.rowcount,   attributes={"db.operation.name": op})

def _inst_fetchall(self):
    rows = _orig_fetchall(self)
    return rows

_MockCursor.execute  = _inst_execute
_MockCursor.fetchall = _inst_fetchall


def rollup_daily_sales(report_date, region):
    conn = psycopg2.connect("host=analytics-db dbname=reporting user=etl")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT order_id, total_usd, items FROM orders WHERE date=%s AND region=%s",
            (report_date, region)
        )
        rows = cur.fetchall()
        total = sum(r[1] for r in rows)

        cur.execute(
            "INSERT INTO daily_sales_rollup (date, region, total_usd, order_count) VALUES (%s,%s,%s,%s)",
            (report_date, region, total, len(rows))
        )
        conn.commit()

        logger.info("daily sales rollup inserted",
                    extra={"report.date": report_date, "report.region": region,
                           "report.total_usd": round(total, 2), "report.order_count": len(rows)})
        return len(rows), round(total, 2)

    conn.close()


print(f"\n[{SVC}] Daily sales rollup via patched psycopg2...")
for date, region in [("2026-03-24", "us-east"), ("2026-03-24", "eu-west"), ("2026-03-24", "apac")]:
    count, total = rollup_daily_sales(date, region)
    print(f"  ✅ {date}  {region:<10}  orders={count}  total=${total:.2f}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
