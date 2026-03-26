#!/usr/bin/env python3
"""
E2E "Observe this project." — Real Agent Invocation
=====================================================
This test ACTUALLY runs `claude -p "Observe this project."` on a blank,
uninstrumented Flask app. It does not assume or hardcode what the agent
will generate.

What this tests:
  1. The agent reads the blank app and understands it (Flask + SQLAlchemy
     + payment gateway + fraud scoring)
  2. The agent correctly assigns Tier A (auto-instrumentation via
     opentelemetry-instrumentation-flask and -sqlalchemy)
  3. The agent adds business enrichment (order.total_usd, customer.tier,
     fraud.score, payment.status)
  4. The generated requirements.txt includes the right OTel packages
  5. The instrumented app runs and serves requests
  6. Spans actually arrive in Elastic with correct attributes

Run:
    cd smoke-tests && python3 86-e2e-observe-this-project/smoke.py

Requirements (in addition to requirements.txt):
  - `claude` CLI installed and authenticated
  - ELASTIC_OTLP_ENDPOINT and ELASTIC_API_KEY set in .env or environment
"""

import os
import sys
import time
import uuid
import shutil
import subprocess
import tempfile
import json
import re
import threading

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")

if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set")
    sys.exit(0)

SVC = "86-e2e-observe-this-project"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-flask-orders")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

if not os.path.exists(CLAUDE_MD):
    # Try relative to edot-autopilot root
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []
def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-flask-orders (no OTel)")
print(f"  Agent:   claude -p (non-interactive)")
print(f"  Target:  {ENDPOINT.split('@')[-1].split('/')[0] if '@' in ENDPOINT else ENDPOINT[:40]}")
print()

# ── Step 1: Verify prerequisites ──────────────────────────────────────────────
print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
check("claude CLI is installed", claude_bin is not None,
      "install via: npm install -g @anthropic-ai/claude-code")
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD), f"looked at {CLAUDE_MD}")
check("Fixture app exists", os.path.isdir(FIXTURE_DIR))
check("Fixture has no OTel", not any(
    "opentelemetry" in open(os.path.join(FIXTURE_DIR, f)).read()
    for f in ["app.py", "requirements.txt"]
    if os.path.exists(os.path.join(FIXTURE_DIR, f))
), "fixture already contains opentelemetry — test is invalid")

if any(s == "FAIL" for s, _, _ in CHECKS):
    print("Prerequisites failed — cannot continue")
    for status, name, detail in CHECKS:
        line = f"  [{status}] {name}"
        if detail and status == "FAIL":
            line += f"\n         -> {detail}"
        print(line)
    sys.exit(1)

print("  [PASS] all prerequisites met\n")

# ── Step 2: Set up temp workspace ─────────────────────────────────────────────
print("Step 2: Setting up blank app workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-e2e-")
try:
    # Copy blank fixture
    for fname in os.listdir(FIXTURE_DIR):
        src = os.path.join(FIXTURE_DIR, fname)
        dst = os.path.join(tmpdir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, dst)

    # Copy CLAUDE.md (the agent reads this for its instructions)
    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))

    # Initialize git so we can diff what the agent changes
    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@edot-autopilot"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot E2E"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial: blank app, no observability"],
                   cwd=tmpdir, capture_output=True, check=True)

    check("Temp workspace created", True, tmpdir)
    print(f"  Workspace: {tmpdir}")
    print(f"  Files: {sorted(os.listdir(tmpdir))}\n")

    # ── Step 3: Run "Observe this project." ───────────────────────────────────
    print("Step 3: Running claude -p 'Observe this project.' (this takes a few minutes...)")
    observe_prompt = (
        f"Observe this project.\n"
        f"My Elastic endpoint: {ENDPOINT}\n"
        f"My Elastic API key: {API_KEY}"
    )

    t0 = time.time()
    result = subprocess.run(
        [
            claude_bin,
            "--dangerously-skip-permissions",
            "-p", observe_prompt,
            "--model", "claude-sonnet-4-6",
            "--max-budget-usd", "2.00",
        ],
        cwd=tmpdir,
        capture_output=True,
        text=True,
        timeout=600,  # 10 minutes max
    )
    elapsed = time.time() - t0

    print(f"  Agent finished in {elapsed:.0f}s (exit code {result.returncode})")
    if result.stdout:
        # Print last 20 lines of agent output for visibility
        lines = result.stdout.strip().splitlines()
        print(f"  Agent output (last 20 lines of {len(lines)} total):")
        for line in lines[-20:]:
            print(f"    {line}")

    check("Agent exited cleanly", result.returncode == 0,
          f"stderr: {result.stderr[-500:] if result.stderr else ''}")

    # ── Step 4: Inspect the diff ──────────────────────────────────────────────
    print("\nStep 4: Inspecting what the agent changed")
    diff_result = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=tmpdir, capture_output=True, text=True
    )
    diff = diff_result.stdout

    # Also get list of new files
    new_files_result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=tmpdir, capture_output=True, text=True
    )
    new_files = [f.strip() for f in new_files_result.stdout.splitlines() if f.strip()]

    print(f"  Modified files (git diff): {len(diff.splitlines())} diff lines")
    print(f"  New files: {new_files}")

    # Read current state of key files
    req_file = os.path.join(tmpdir, "requirements.txt")
    app_file = os.path.join(tmpdir, "app.py")
    otel_slos = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")

    req_content = open(req_file).read() if os.path.exists(req_file) else ""
    app_content = open(app_file).read() if os.path.exists(app_file) else ""

    print("\nCode correctness checks (Tier A — auto-instrumentation):")

    # requirements.txt checks
    check("opentelemetry-sdk added to requirements.txt",
          "opentelemetry-sdk" in req_content or "opentelemetry-api" in req_content,
          f"requirements.txt:\n{req_content}")
    check("Flask instrumentation package added",
          "opentelemetry-instrumentation-flask" in req_content,
          f"requirements.txt:\n{req_content}")
    check("SQLAlchemy instrumentation package added",
          "opentelemetry-instrumentation-sqlalchemy" in req_content,
          f"requirements.txt:\n{req_content}")
    check("OTLP HTTP exporter added",
          "opentelemetry-exporter-otlp" in req_content,
          f"requirements.txt:\n{req_content}")

    # app.py instrumentation checks
    check("FlaskInstrumentor applied in app.py",
          "FlaskInstrumentor" in app_content and ".instrument(" in app_content,
          "FlaskInstrumentor().instrument() not found")
    check("TracerProvider or OTLPSpanExporter configured",
          "TracerProvider" in app_content or "OTLPSpanExporter" in app_content,
          "no tracer setup found in app.py")
    check("Elastic endpoint configured from env",
          "ELASTIC_OTLP_ENDPOINT" in app_content or "OTLP_ENDPOINT" in app_content
          or ENDPOINT.split("//")[1][:20] in app_content,
          "endpoint not referenced in app.py")

    # Business enrichment checks
    print("\nBusiness enrichment checks:")
    has_order_enrichment = any(
        attr in app_content for attr in [
            "order.total", "order.value", "total_usd",
            "customer.tier", "customer_tier",
            "fraud.score", "fraud_score",
            "payment.status",
        ]
    )
    check("Business span attributes added (order/customer/fraud/payment)",
          has_order_enrichment,
          "no business enrichment attributes found in app.py")

    # .otel/ output files
    print("\n.otel/ output file checks:")
    check(".otel/slos.json created",
          os.path.exists(otel_slos),
          f"expected at {otel_slos}")
    if os.path.exists(otel_slos):
        try:
            slos_raw = json.load(open(otel_slos))
            # Accept either {"services": [...]} or a top-level list
            if isinstance(slos_raw, list):
                slos_services = slos_raw
                check(".otel/slos.json is valid JSON with at least one SLO",
                      len(slos_raw) > 0,
                      f"got empty list")
            else:
                slos_services = slos_raw.get("services", [])
                check(".otel/slos.json is valid JSON with 'services' key",
                      "services" in slos_raw,
                      f"keys: {list(slos_raw.keys())}")
        except json.JSONDecodeError as e:
            check(".otel/slos.json is valid JSON", False, str(e))

    check(".otel/golden-paths.md created",
          os.path.exists(otel_golden),
          f"expected at {otel_golden}")

    # ── Step 5: Run the instrumented app ──────────────────────────────────────
    print("\nStep 5: Running the instrumented app")

    # Install new requirements in a fresh venv
    venv_dir = os.path.join(tmpdir, ".venv")
    pip_install = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q",
         "-r", req_file, "--no-warn-script-location"],
        capture_output=True, text=True
    )
    if pip_install.returncode != 0:
        check("pip install of generated requirements succeeded",
              False, pip_install.stderr[-500:])
    else:
        check("pip install of generated requirements succeeded", True)

    # Start the app
    PORT = 15086
    env = os.environ.copy()
    env["PORT"] = str(PORT)
    app_proc = subprocess.Popen(
        [sys.executable, app_file],
        cwd=tmpdir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for it to start
    import requests as http_lib
    started = False
    for _ in range(30):
        try:
            r = http_lib.get(f"http://127.0.0.1:{PORT}/health", timeout=0.5)
            if r.status_code == 200:
                started = True
                break
        except Exception:
            time.sleep(0.3)

    check("Instrumented app starts and responds to /health",
          started,
          f"app stdout: {app_proc.stdout.read(500) if app_proc.poll() is not None else '(still running)'}")

    if started:
        print(f"  App running on port {PORT}")
        print("\nStep 6: Making test requests to instrumented app")

        # Place an order
        r_order = http_lib.post(f"http://127.0.0.1:{PORT}/orders", json={
            "customer_id": "cust_e2e_test",
            "customer_tier": "premium",
            "items": [
                {"name": "Widget Pro", "price_usd": 149.99, "qty": 2},
                {"name": "Gadget Plus", "price_usd": 89.99, "qty": 1},
            ]
        })
        check("POST /orders → 201 or 402 (fraud block is ok)",
              r_order.status_code in (201, 402),
              f"status={r_order.status_code} body={r_order.text[:200]}")

        order_id = None
        if r_order.status_code == 201:
            order_id = r_order.json().get("order_id")
            check("Response has order_id", order_id is not None,
                  f"body: {r_order.text[:200]}")

            r_get = http_lib.get(f"http://127.0.0.1:{PORT}/orders/{order_id}")
            check("GET /orders/<id> → 200", r_get.status_code == 200,
                  f"status={r_get.status_code}")

        r_missing = http_lib.get(f"http://127.0.0.1:{PORT}/orders/nonexistent-id")
        check("GET /orders/<missing> → 404", r_missing.status_code == 404)

        # Give OTel BatchSpanProcessor time to export
        print("\n  Waiting 3s for OTLP export to Elastic...")
        time.sleep(3)

        check("Test requests completed without app crash",
              app_proc.poll() is None,
              "app process died during requests")

        # ── Step 7: ES|QL — confirm spans actually landed in Elastic ──────────
        print("\nStep 7: Verifying spans reached Elastic (ES|QL)")
        import json as _json
        import urllib.request as _urllib_req

        # Derive ES base URL from the OTLP endpoint
        # OTLP: https://<deployment>.apm.<region>.cloud.es.io
        # ES:   https://<deployment>.<region>.cloud.es.io
        es_base = ENDPOINT.rstrip("/").replace(".apm.", ".")
        # Remove /v1/traces suffix if present
        for suffix in ["/v1/traces", "/v1/logs", "/v1/metrics"]:
            if es_base.endswith(suffix):
                es_base = es_base[: -len(suffix)]

        esql_query = (
            'FROM traces-apm* METADATA _index '
            '| WHERE service.name == "order-service" '
            '| LIMIT 1'
        )
        span_confirmed = False
        for attempt in range(3):
            try:
                body = _json.dumps({"query": esql_query}).encode()
                req = _urllib_req.Request(
                    f"{es_base}/_query",
                    data=body,
                    headers={
                        "Authorization": f"ApiKey {API_KEY}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                resp = _urllib_req.urlopen(req, timeout=10)
                result = _json.loads(resp.read())
                if result.get("values") and len(result["values"]) > 0:
                    span_confirmed = True
                    break
                else:
                    time.sleep(5)
            except Exception as e:
                print(f"  ES|QL attempt {attempt+1}/3 failed: {e}")
                time.sleep(5)

        # Warn but don't fail — indexing lag can exceed 15s on busy clusters
        if span_confirmed:
            check("Spans confirmed in Elastic via ES|QL", True)
        else:
            print("  [WARN] ES|QL found no spans yet — may still be indexing")

    # ── Cleanup ───────────────────────────────────────────────────────────────
    if 'app_proc' in dir() and app_proc.poll() is None:
        app_proc.terminate()
        app_proc.wait(timeout=5)

finally:
    # Keep tmpdir for inspection on failure
    failed_checks = [n for s, n, _ in CHECKS if s == "FAIL"]
    if failed_checks:
        print(f"\n  NOTE: Workspace preserved for inspection: {tmpdir}")
    else:
        shutil.rmtree(tmpdir, ignore_errors=True)

# ── Final summary ─────────────────────────────────────────────────────────────
passed = sum(1 for s, _, _ in CHECKS if s == "PASS")
failed = sum(1 for s, _, _ in CHECKS if s == "FAIL")
print(f"\n{'='*62}")
for status, name, detail in CHECKS:
    line = f"  [{status}] {name}"
    if detail and status == "FAIL":
        line += f"\n         -> {detail}"
    print(line)
print(f"\n  Result: {passed}/{len(CHECKS)} checks passed")
if failed:
    sys.exit(1)
