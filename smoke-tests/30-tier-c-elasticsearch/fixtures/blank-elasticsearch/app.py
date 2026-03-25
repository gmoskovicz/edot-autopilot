"""
Product Search Index — Elasticsearch via elasticsearch-py

No observability. Run `Observe this project.` to add it.
"""

import uuid
import time


# ── Mock Elasticsearch client (simulates real elasticsearch-py without a cluster) ──
_index_store = {}


class _MockES:
    def __init__(self, hosts=None, **kwargs):
        pass

    def index(self, index, body, id=None, **kwargs):
        time.sleep(0.015)
        doc_id = id or uuid.uuid4().hex
        _index_store.setdefault(index, {})[doc_id] = {**body, "_id": doc_id}
        return {
            "_id": doc_id,
            "_index": index,
            "result": "created",
            "_shards": {"successful": 1},
        }

    def search(self, index, body, **kwargs):
        time.sleep(0.02)
        docs = list(_index_store.get(index, {}).values())[:5]
        return {
            "hits": {
                "total": {"value": len(docs)},
                "hits": [{"_source": d, "_id": d["_id"]} for d in docs],
            }
        }

    def update(self, index, id, body, **kwargs):
        time.sleep(0.012)
        if index in _index_store and id in _index_store[index]:
            _index_store[index][id].update(body.get("doc", {}))
        return {"_id": id, "result": "updated", "_shards": {"successful": 1}}


class Elasticsearch:
    def __new__(cls, *args, **kwargs):
        return _MockES(*args, **kwargs)


# ── Application code ───────────────────────────────────────────────────────────

def sync_product_catalog(products):
    """Index products, search to verify, then update stock status."""
    es = Elasticsearch(hosts=["https://search.internal:9200"])

    for product in products:
        result = es.index(index="products", body=product, id=product["sku"])
        print(f"  Indexed: {product['sku']} → {result['result']}")

    results = es.search(index="products", body={"query": {"match_all": {}}})
    print(f"  Search found {results['hits']['total']['value']} docs")

    for doc in results["hits"]["hits"]:
        es.update(
            index="products",
            id=doc["_id"],
            body={"doc": {"stock_updated": True}},
        )

    return results["hits"]["total"]["value"]


if __name__ == "__main__":
    products = [
        {"sku": "SKU-A001", "name": "Widget Pro", "category": "electronics",
         "price_usd": 299.99, "stock": 48, "_id": "SKU-A001"},
        {"sku": "SKU-B002", "name": "Gadget Plus", "category": "electronics",
         "price_usd": 149.99, "stock": 120, "_id": "SKU-B002"},
        {"sku": "SKU-C003", "name": "Component X", "category": "components",
         "price_usd": 12.50, "stock": 500, "_id": "SKU-C003"},
    ]

    found = sync_product_catalog(products)
    print(f"Sync complete — {found} documents in index")
