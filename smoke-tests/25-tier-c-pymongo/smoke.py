#!/usr/bin/env python3
"""
Smoke test: Tier C — PyMongo client (monkey-patched).

Patches Collection.insert_one / find / update_one.
Business scenario: Product catalog service — seasonal price updates,
stock level writes, search index sync.

Run:
    cd smoke-tests && python3 25-tier-c-pymongo/smoke.py
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

SVC = "smoke-tier-c-pymongo"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

mongo_ops    = meter.create_counter("mongodb.operations")
mongo_latency= meter.create_histogram("mongodb.operation_ms", unit="ms")

_collections = {}


class _MockCollection:
    def __init__(self, name, db_name):
        self.name    = name
        self.db_name = db_name
        if name not in _collections:
            _collections[name] = {}

    def insert_one(self, document):
        time.sleep(0.01)
        doc_id = str(uuid.uuid4())
        _collections[self.name][doc_id] = {**document, "_id": doc_id}
        return type("InsertResult", (), {"inserted_id": doc_id})()

    def find(self, filter_=None, **kwargs):
        time.sleep(0.015)
        docs = list(_collections.get(self.name, {}).values())
        return docs

    def update_one(self, filter_, update, upsert=False):
        time.sleep(0.012)
        matched = len(_collections.get(self.name, {})) > 0
        return type("UpdateResult", (), {"matched_count": 1 if matched else 0,
                                         "modified_count": 1 if matched else 0})()

class _MockDatabase:
    def __init__(self, name):
        self.name = name
    def __getitem__(self, collection_name):
        return _MockCollection(collection_name, self.name)
    def get_collection(self, name):
        return _MockCollection(name, self.name)

class _MockClient:
    def __init__(self, *args, **kwargs): pass
    def __getitem__(self, db_name):
        return _MockDatabase(db_name)

class pymongo:
    MongoClient = _MockClient


_orig_insert = _MockCollection.insert_one
_orig_find   = _MockCollection.find
_orig_update = _MockCollection.update_one

def _inst_insert(self, document):
    t0 = time.time()
    with tracer.start_as_current_span("mongodb.insert_one", kind=SpanKind.CLIENT,
        attributes={"db.system": "mongodb", "db.name": self.db_name,
                    "db.mongodb.collection": self.name, "db.operation": "insert"}) as span:
        result = _orig_insert(self, document)
        dur = (time.time() - t0) * 1000
        span.set_attribute("db.mongodb.inserted_id", str(result.inserted_id))
        mongo_ops.add(1, attributes={"db.operation": "insert", "db.mongodb.collection": self.name})
        mongo_latency.record(dur, attributes={"db.operation": "insert"})
        return result

def _inst_find(self, filter_=None, **kwargs):
    t0 = time.time()
    with tracer.start_as_current_span("mongodb.find", kind=SpanKind.CLIENT,
        attributes={"db.system": "mongodb", "db.name": self.db_name,
                    "db.mongodb.collection": self.name, "db.operation": "find"}) as span:
        results = _orig_find(self, filter_, **kwargs)
        dur = (time.time() - t0) * 1000
        span.set_attribute("db.mongodb.result_count", len(results))
        mongo_ops.add(1, attributes={"db.operation": "find", "db.mongodb.collection": self.name})
        mongo_latency.record(dur, attributes={"db.operation": "find"})
        return results

def _inst_update(self, filter_, update, upsert=False):
    t0 = time.time()
    with tracer.start_as_current_span("mongodb.update_one", kind=SpanKind.CLIENT,
        attributes={"db.system": "mongodb", "db.name": self.db_name,
                    "db.mongodb.collection": self.name, "db.operation": "update",
                    "db.mongodb.upsert": upsert}) as span:
        result = _inst_update.__wrapped__(self, filter_, update, upsert)
        dur = (time.time() - t0) * 1000
        span.set_attribute("db.mongodb.matched_count",  result.matched_count)
        span.set_attribute("db.mongodb.modified_count", result.modified_count)
        mongo_ops.add(1, attributes={"db.operation": "update", "db.mongodb.collection": self.name})
        mongo_latency.record(dur, attributes={"db.operation": "update"})
        return result

_inst_update.__wrapped__ = _orig_update
_MockCollection.insert_one = _inst_insert
_MockCollection.find       = _inst_find
_MockCollection.update_one = _inst_update


def apply_seasonal_discount(category, discount_pct):
    client   = pymongo.MongoClient("mongodb://catalog-db:27017")
    products = client["catalog"]["products"]
    existing = products.find({"category": category})

    for product in existing:
        new_price = round(product.get("price_usd", 100) * (1 - discount_pct / 100), 2)
        products.update_one({"_id": product["_id"]}, {"$set": {"price_usd": new_price,
                                                                "discount_pct": discount_pct}})
        logger.info("product price updated",
                    extra={"product.sku": product.get("sku", ""), "product.category": category,
                           "discount.pct": discount_pct, "product.new_price_usd": new_price})

    products.insert_one({"sku": f"SKU-{uuid.uuid4().hex[:6].upper()}", "category": category,
                          "price_usd": 49.99, "discount_pct": discount_pct,
                          "name": f"New {category} item"})
    print(f"  ✅ {category:<15}  discount={discount_pct}%  updated={len(existing)} products")


print(f"\n[{SVC}] Product catalog operations via patched PyMongo...")
apply_seasonal_discount("electronics",  15)
apply_seasonal_discount("clothing",     25)
apply_seasonal_discount("home-goods",   10)

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
