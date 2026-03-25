#!/usr/bin/env python3
"""
Smoke test: Tier C — elasticsearch-py client (monkey-patched).

Patches Elasticsearch.index / search / update.
Business scenario: Product search index — index new products, search by
category, update stock levels.

Run:
    cd smoke-tests && python3 30-tier-c-elasticsearch/smoke.py
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

SVC = "smoke-tier-c-elasticsearch"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

es_ops    = meter.create_counter("elasticsearch.operations")
es_latency= meter.create_histogram("elasticsearch.operation_ms", unit="ms")
es_hits   = meter.create_histogram("elasticsearch.search_hits")

_index_store = {}


class _MockES:
    def __init__(self, hosts=None, **kwargs): pass

    def index(self, index, body, id=None, **kwargs):
        time.sleep(0.015)
        doc_id = id or uuid.uuid4().hex
        _index_store.setdefault(index, {})[doc_id] = {**body, "_id": doc_id}
        return {"_id": doc_id, "_index": index, "result": "created", "_shards": {"successful": 1}}

    def search(self, index, body, **kwargs):
        time.sleep(0.02)
        docs = list(_index_store.get(index, {}).values())[:5]
        return {"hits": {"total": {"value": len(docs)},
                         "hits": [{"_source": d, "_id": d["_id"]} for d in docs]}}

    def update(self, index, id, body, **kwargs):
        time.sleep(0.012)
        if index in _index_store and id in _index_store[index]:
            _index_store[index][id].update(body.get("doc", {}))
        return {"_id": id, "result": "updated", "_shards": {"successful": 1}}

class Elasticsearch:
    def __new__(cls, *args, **kwargs):
        return _MockES(*args, **kwargs)


_orig_index  = _MockES.index
_orig_search = _MockES.search
_orig_update = _MockES.update

def _inst_index(self, index, body, id=None, **kwargs):
    t0 = time.time()
    with tracer.start_as_current_span("elasticsearch.index", kind=SpanKind.CLIENT,
        attributes={"db.system": "elasticsearch", "elasticsearch.index": index,
                    "db.operation": "index"}) as span:
        result = _orig_index(self, index, body, id, **kwargs)
        dur = (time.time() - t0) * 1000
        span.set_attribute("elasticsearch.doc_id",     result["_id"])
        span.set_attribute("elasticsearch.result",     result["result"])
        es_ops.add(1, attributes={"elasticsearch.operation": "index", "elasticsearch.index": index})
        es_latency.record(dur, attributes={"elasticsearch.operation": "index"})
        return result

def _inst_search(self, index, body, **kwargs):
    t0 = time.time()
    with tracer.start_as_current_span("elasticsearch.search", kind=SpanKind.CLIENT,
        attributes={"db.system": "elasticsearch", "elasticsearch.index": index,
                    "db.operation": "search"}) as span:
        result = _orig_search(self, index, body, **kwargs)
        hits = result["hits"]["total"]["value"]
        dur  = (time.time() - t0) * 1000
        span.set_attribute("elasticsearch.hits_total", hits)
        es_ops.add(1, attributes={"elasticsearch.operation": "search", "elasticsearch.index": index})
        es_latency.record(dur, attributes={"elasticsearch.operation": "search"})
        es_hits.record(hits, attributes={"elasticsearch.index": index})
        return result

def _inst_update(self, index, id, body, **kwargs):
    t0 = time.time()
    with tracer.start_as_current_span("elasticsearch.update", kind=SpanKind.CLIENT,
        attributes={"db.system": "elasticsearch", "elasticsearch.index": index,
                    "db.operation": "update", "elasticsearch.doc_id": id}) as span:
        result = _orig_update(self, index, id, body, **kwargs)
        es_ops.add(1, attributes={"elasticsearch.operation": "update", "elasticsearch.index": index})
        es_latency.record((time.time() - t0) * 1000, attributes={"elasticsearch.operation": "update"})
        return result

_MockES.index  = _inst_index
_MockES.search = _inst_search
_MockES.update = _inst_update


def sync_product_catalog(products):
    es = Elasticsearch(hosts=["https://search.internal:9200"])
    for product in products:
        result = es.index(index="products", body=product, id=product["sku"])
        logger.info("product indexed", extra={"product.sku": product["sku"],
                    "product.category": product["category"], "es.doc_id": result["_id"]})

    results = es.search(index="products", body={"query": {"match_all": {}}})
    print(f"  ✅ indexed {len(products)} products, found {results['hits']['total']['value']} in index")

    for doc in results["hits"]["hits"]:
        es.update(index="products", id=doc["_id"], body={"doc": {"stock_updated": True}})


products = [
    {"sku": "SKU-A001", "name": "Widget Pro",   "category": "electronics", "price_usd": 299.99, "stock": 48,  "_id": "SKU-A001"},
    {"sku": "SKU-B002", "name": "Gadget Plus",  "category": "electronics", "price_usd": 149.99, "stock": 120, "_id": "SKU-B002"},
    {"sku": "SKU-C003", "name": "Component X",  "category": "components",  "price_usd": 12.50,  "stock": 500, "_id": "SKU-C003"},
]

print(f"\n[{SVC}] Product catalog via patched elasticsearch-py...")
sync_product_catalog(products)

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
