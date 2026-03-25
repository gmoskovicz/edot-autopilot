"""
Analytics Warehouse ETL — PostgreSQL via psycopg2

No observability. Run `Observe this project.` to add it.
"""

import uuid
import random
import time


# ── Mock psycopg2 (simulates real psycopg2 without a PostgreSQL server) ─────────

class _MockCursor:
    def __init__(self, conn):
        self._conn = conn
        self.rowcount = 0
        self._last_query = ""
        self._results = []

    def execute(self, query, params=None):
        time.sleep(0.02)
        self._last_query = query.strip()[:80]
        self.rowcount = random.randint(1, 50)
        self._results = [
            (uuid.uuid4().hex[:8], random.uniform(100, 5000), random.randint(1, 200))
            for _ in range(min(5, self.rowcount))
        ]

    def fetchall(self):
        return self._results

    def fetchone(self):
        return self._results[0] if self._results else None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


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


# ── Application code ───────────────────────────────────────────────────────────

def rollup_daily_sales(report_date, region):
    """Aggregate daily sales from orders table and write to the rollup table."""
    conn = psycopg2.connect("host=analytics-db dbname=reporting user=etl")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT order_id, total_usd, items FROM orders WHERE date=%s AND region=%s",
            (report_date, region),
        )
        rows = cur.fetchall()
        total = sum(r[1] for r in rows)

        cur.execute(
            "INSERT INTO daily_sales_rollup (date, region, total_usd, order_count)"
            " VALUES (%s,%s,%s,%s)",
            (report_date, region, total, len(rows)),
        )
        conn.commit()
        print(f"Rollup {report_date}/{region}: {len(rows)} orders, ${total:.2f}")
        return len(rows), round(total, 2)

    conn.close()


if __name__ == "__main__":
    for date, region in [
        ("2026-03-24", "us-east"),
        ("2026-03-24", "eu-west"),
        ("2026-03-24", "apac"),
    ]:
        count, total = rollup_daily_sales(date, region)
