"""
Verification Target — minimal Flask app (no OTel)

This fixture is used by 06-verify to confirm the OTLP endpoint is reachable
and that spans can be queried back from Elasticsearch.

Run `Observe this project.` to add observability, then use check_spans.py
to verify spans arrive in Elastic.
"""

import os
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/ping")
def ping():
    return jsonify({"pong": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5006))
    app.run(host="0.0.0.0", port=port)
