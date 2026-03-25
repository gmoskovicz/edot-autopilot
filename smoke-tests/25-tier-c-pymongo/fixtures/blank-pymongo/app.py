"""
Product Catalog Service — MongoDB via pymongo

No observability. Run `Observe this project.` to add it.
"""

import uuid
import time


# ── Mock pymongo client (simulates real pymongo without a MongoDB server) ───────
_collections = {}


class _MockCollection:
    def __init__(self, name, db_name):
        self.name = name
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
        return type("UpdateResult", (), {
            "matched_count": 1 if matched else 0,
            "modified_count": 1 if matched else 0,
        })()


class _MockDatabase:
    def __init__(self, name):
        self.name = name

    def __getitem__(self, collection_name):
        return _MockCollection(collection_name, self.name)

    def get_collection(self, name):
        return _MockCollection(name, self.name)


class _MockClient:
    def __init__(self, *args, **kwargs):
        pass

    def __getitem__(self, db_name):
        return _MockDatabase(db_name)


class pymongo:
    MongoClient = _MockClient


# ── Application code ───────────────────────────────────────────────────────────

def apply_seasonal_discount(category, discount_pct):
    """Apply a seasonal discount to all products in a category, then insert a new listing."""
    client = pymongo.MongoClient("mongodb://catalog-db:27017")
    products = client["catalog"]["products"]

    existing = products.find({"category": category})
    for product in existing:
        new_price = round(product.get("price_usd", 100) * (1 - discount_pct / 100), 2)
        products.update_one(
            {"_id": product["_id"]},
            {"$set": {"price_usd": new_price, "discount_pct": discount_pct}},
        )
        print(f"  Updated {product.get('sku', '?')} price to ${new_price}")

    products.insert_one({
        "sku": f"SKU-{uuid.uuid4().hex[:6].upper()}",
        "category": category,
        "price_usd": 49.99,
        "discount_pct": discount_pct,
        "name": f"New {category} item",
    })


if __name__ == "__main__":
    for category, discount_pct in [("electronics", 15), ("clothing", 25), ("home-goods", 10)]:
        print(f"Applying {discount_pct}% discount to {category}...")
        apply_seasonal_discount(category, discount_pct)
    print("Done")
