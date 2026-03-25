"""
Currency Exchange Rate Fetcher — httpx HTTP client

No observability. Run `Observe this project.` to add it.
"""

import uuid
import time
import random


# ── FX rate reference table ────────────────────────────────────────────────────
FX_RATES = {
    "USD/EUR": 0.92,
    "USD/GBP": 0.79,
    "USD/JPY": 149.8,
    "USD/BRL": 5.07,
    "EUR/USD": 1.09,
}


# ── Mock httpx client (simulates real httpx without network access) ─────────────

class _MockResponse:
    def __init__(self, status_code, json_data, url):
        self.status_code = status_code
        self._json = json_data
        self.url = url
        self.headers = {
            "content-type": "application/json",
            "x-request-id": uuid.uuid4().hex,
        }

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
        # Reconstruct pair as "BASE/QUOTE" from path segments like ".../USD/EUR"
        parts = url.rstrip("/").split("/")
        if len(parts) >= 2:
            pair = f"{parts[-2]}/{parts[-1]}"
        rate = FX_RATES.get(pair, 1.0) * random.uniform(0.998, 1.002)
        return _MockResponse(200, {"pair": pair, "rate": round(rate, 4),
                                   "timestamp": int(time.time())}, url)

    def post(self, url, **kwargs):
        time.sleep(random.uniform(0.01, 0.04))
        return _MockResponse(201, {
            "stored": True,
            "key": kwargs.get("json", {}).get("key"),
        }, url)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class httpx:
    Client = _MockHttpxClient


# ── Application code ───────────────────────────────────────────────────────────

def fetch_fx_rate(base, quote):
    """Fetch an FX rate from the provider API and cache it."""
    with httpx.Client() as client:
        resp = client.get(
            f"https://api.fx-provider.io/v2/rates/{base}/{quote}",
            headers={"Authorization": "Bearer fx-api-key"},
        )
        resp.raise_for_status()
        data = resp.json()

        client.post(
            "https://api.fx-provider.io/v2/cache/store",
            json={"key": f"fx:{base}:{quote}", "value": data["rate"], "ttl": 300},
        )

        print(f"  {base}/{quote} = {data['rate']}")
        return data["rate"]


if __name__ == "__main__":
    pairs = [("USD", "EUR"), ("USD", "GBP"), ("USD", "JPY"), ("EUR", "USD"), ("USD", "BRL")]
    for base, quote in pairs:
        try:
            fetch_fx_rate(base, quote)
        except Exception as e:
            print(f"  {base}/{quote} failed: {e}")
