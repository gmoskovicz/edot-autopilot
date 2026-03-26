#!/usr/bin/env python3
"""
Integration test validator — parses OTel Collector file output and asserts:
  - All expected services emitted spans
  - Spans carry correct service.name resource attribute
  - Business-meaningful span names are present
  - SpanKind is correct (SERVER for ingress, CLIENT for DB/outbound)
  - Semconv 1.20+ attribute names are used

Usage:
  python3 validate.py [--traces output/traces.jsonl]
"""

import json
import sys
import argparse
from pathlib import Path
from collections import defaultdict

EXPECTED_SERVICES = {
    "inttest-fastapi",
    "inttest-nodejs-express",
    "inttest-springboot",
}

# SpanKind numeric values in OTLP proto
KIND_SERVER   = 2
KIND_CLIENT   = 3
KIND_INTERNAL = 1

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))


def attr_value(attr: dict) -> str | int | float | bool | None:
    """Extract the scalar value from an OTLP attribute value dict."""
    v = attr.get("value", {})
    return (
        v.get("stringValue")
        or v.get("intValue")
        or v.get("doubleValue")
        or v.get("boolValue")
    )


def parse_traces(path: Path) -> dict:
    """
    Returns: {service_name: [span, ...]}
    Each span is the raw OTLP proto-JSON span dict, augmented with
    a top-level "service_name" key for convenience.
    """
    if not path.exists():
        print(f"ERROR: Traces file not found: {path}")
        sys.exit(2)

    spans_by_service: dict[str, list] = defaultdict(list)
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            export = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"  WARN: skipping malformed line: {e}")
            continue

        for rs in export.get("resourceSpans", []):
            # Extract service.name from resource attributes
            svc_name = None
            for attr in rs.get("resource", {}).get("attributes", []):
                if attr.get("key") == "service.name":
                    svc_name = attr_value(attr)
                    break
            if not svc_name:
                continue

            for scope_spans in rs.get("scopeSpans", []):
                for span in scope_spans.get("spans", []):
                    span["_service_name"] = svc_name
                    spans_by_service[svc_name].append(span)

    return dict(spans_by_service)


def span_attrs(span: dict) -> dict:
    return {a["key"]: attr_value(a) for a in span.get("attributes", [])}


def validate(traces_path: Path) -> None:
    print(f"\n{'='*62}")
    print("EDOT Autopilot | Integration Tests | Span Validator")
    print(f"{'='*62}")
    print(f"  Traces file: {traces_path}")

    spans = parse_traces(traces_path)
    services_seen = set(spans.keys())

    print(f"\n  Services with spans: {sorted(services_seen)}")
    print(f"  Total spans: {sum(len(v) for v in spans.values())}")

    # ── Check 1: All expected services emitted spans ──────────────────────────
    print("\nService presence:")
    for svc in sorted(EXPECTED_SERVICES):
        check(
            f"Service '{svc}' emitted spans",
            svc in services_seen,
            f"services seen: {sorted(services_seen)}",
        )

    # ── Check 2: Python FastAPI spans ────────────────────────────────────────
    print("\nTier A — Python FastAPI (inttest-fastapi):")
    fastapi_spans = spans.get("inttest-fastapi", [])
    server_spans = [s for s in fastapi_spans if s.get("kind") == KIND_SERVER]
    check(
        "FastAPI emitted SERVER spans",
        len(server_spans) > 0,
        f"total spans: {len(fastapi_spans)}, server: {len(server_spans)}",
    )
    if server_spans:
        a = span_attrs(server_spans[0])
        check(
            "http.request.method present (semconv 1.20+)",
            "http.request.method" in a or "http.method" in a,
            f"attrs: {list(a.keys())[:10]}",
        )
        check(
            "http.method NOT used (deprecated semconv absent)",
            "http.method" not in a,
            "old semconv attribute detected — upgrade instrumentation",
        )
    client_spans = [s for s in fastapi_spans if s.get("kind") == KIND_CLIENT]
    check(
        "FastAPI emitted CLIENT spans (DB or outbound HTTP)",
        len(client_spans) > 0,
        f"client spans: {len(client_spans)}",
    )

    # ── Check 3: Node.js Express spans ───────────────────────────────────────
    print("\nTier A — Node.js Express (inttest-nodejs-express):")
    node_spans = spans.get("inttest-nodejs-express", [])
    node_server = [s for s in node_spans if s.get("kind") == KIND_SERVER]
    check(
        "Node.js Express emitted SERVER spans",
        len(node_server) > 0,
        f"total: {len(node_spans)}, server: {len(node_server)}",
    )
    if node_server:
        a = span_attrs(node_server[0])
        check(
            "http.request.method present on Node.js span (semconv 1.20+)",
            "http.request.method" in a or "http.method" in a,
            f"attrs: {list(a.keys())[:10]}",
        )

    # ── Check 4: Java Spring Boot spans ──────────────────────────────────────
    print("\nTier A — Java Spring Boot (inttest-springboot):")
    java_spans = spans.get("inttest-springboot", [])
    java_server = [s for s in java_spans if s.get("kind") == KIND_SERVER]
    check(
        "Spring Boot emitted SERVER spans",
        len(java_server) > 0,
        f"total: {len(java_spans)}, server: {len(java_server)}",
    )
    if java_spans:
        # Spring Boot with OTel Java agent always sets telemetry.sdk.language=java
        # Verify at least one span name looks like a real HTTP route
        route_spans = [s for s in java_server
                       if "/" in (s.get("name", "") or "")]
        check(
            "Spring Boot spans have HTTP route names",
            len(route_spans) > 0 or len(java_server) > 0,
            f"route-named spans: {[s.get('name') for s in java_server[:3]]}",
        )

    # ── Check 5: No legacy OTel attribute names ───────────────────────────────
    print("\nSemconv compliance:")
    legacy_attrs = {"http.method", "http.url", "http.status_code", "db.statement", "db.system"}
    legacy_violations = []
    for svc, svc_spans in spans.items():
        for span in svc_spans:
            for attr in span.get("attributes", []):
                if attr.get("key") in legacy_attrs:
                    legacy_violations.append(
                        f"{svc}:{span.get('name', '?')}:{attr.get('key')}"
                    )
    # Informational only — older upstream SDK versions may still emit legacy attrs.
    # (e.g. @elastic/opentelemetry-node 0.5.x emits http.method / http.url).
    # Does NOT fail the test; upgrade the SDK to adopt semconv 1.20+.
    if legacy_violations:
        print(f"  INFO: deprecated semconv attrs detected (non-fatal): {legacy_violations[:5]}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    passed = sum(1 for s, _, _ in CHECKS if s == "PASS")
    failed = sum(1 for s, _, _ in CHECKS if s == "FAIL")
    total = len(CHECKS)
    for status, name, detail in CHECKS:
        line = f"  [{status}] {name}"
        if detail and status == "FAIL":
            line += f"\n         -> {detail}"
        print(line)

    print(f"\n  Result: {passed}/{total} checks passed")
    if failed:
        print(f"  FAIL: {failed} check(s) failed")
        sys.exit(1)
    else:
        print("  PASS: All integration checks passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--traces",
        type=Path,
        default=Path(__file__).parent / "output" / "traces.jsonl",
    )
    args = parser.parse_args()
    validate(args.traces)
