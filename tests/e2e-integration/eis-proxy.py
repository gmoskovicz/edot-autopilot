#!/usr/bin/env python3
"""
EIS Auth Proxy — translates Claude Code CLI auth to Elastic EIS auth.

Claude Code CLI sends:   x-api-key: <key>
Elastic EIS expects:     Authorization: ApiKey <key>

Listens on localhost, rewrites the auth header, and forwards every
request (including SSE streaming responses) to the real EIS endpoint.

Usage:
    python3 eis-proxy.py --target URL [--port 9999]

Environment:
    ANTHROPIC_API_KEY  — key to inject into Authorization: ApiKey header
"""

import argparse
import http.server
import os
import sys
import urllib.error
import urllib.request


def make_handler(target: str, api_key: str) -> type:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)

            # Claude Code appends /v1/messages (and query params) to ANTHROPIC_BASE_URL.
            # EIS expects POST directly to the inference endpoint with no extra path.
            # Strip the Claude-added path and forward straight to the target URL.
            url = target.rstrip("/")

            # Translate auth: drop x-api-key, inject Authorization: ApiKey
            headers: dict[str, str] = {
                "Authorization": f"ApiKey {api_key}",
                "Content-Type": self.headers.get("Content-Type", "application/json"),
            }
            # Forward Anthropic-specific headers that EIS may need
            for h in ("anthropic-version", "anthropic-beta", "x-stainless-arch",
                      "x-stainless-os", "x-stainless-lang", "x-stainless-runtime",
                      "x-stainless-runtime-version", "x-stainless-package-version"):
                if h in self.headers:
                    headers[h] = self.headers[h]

            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    self.send_response(resp.status)
                    for k, v in resp.headers.items():
                        if k.lower() not in ("transfer-encoding", "connection"):
                            self.send_header(k, v)
                    self.end_headers()
                    # Stream response in chunks (needed for SSE / streaming JSON)
                    while chunk := resp.read(4096):
                        self.wfile.write(chunk)
                    self.wfile.flush()
            except urllib.error.HTTPError as exc:
                err_body = exc.read()
                self.send_response(exc.code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_body)))
                self.end_headers()
                self.wfile.write(err_body)

        def log_message(self, fmt: str, *args: object) -> None:
            pass  # suppress per-request noise; startup message is enough

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True,
                        help="Real EIS base URL (e.g. https://host/_inference/anthropic/<id>)")
    parser.add_argument("--port", type=int, default=9999,
                        help="Port to listen on (default: 9999)")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    handler_class = make_handler(args.target, api_key)
    server = http.server.HTTPServer(("127.0.0.1", args.port), handler_class)
    print(
        f"EIS proxy ready: http://127.0.0.1:{args.port} → {args.target}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
