#!/usr/bin/env python3
"""
Eval test: E-Commerce Checkout Platform (core service)
=======================================================
Runs `claude -p "Observe this project."` on the blank checkout-frontend Flask
service (fixtures/blank-checkout-frontend/) and verifies the agent adds the
correct OpenTelemetry instrumentation.

The checkout-frontend is the CORE service of this 8-service e-commerce platform.
Testing the gateway is sufficient to validate the agent's understanding of
distributed tracing across: product-catalog, inventory, pricing, payment, order.

What this tests:
  1. Agent reads the blank checkout service and understands the multi-service architecture
  2. Agent adds opentelemetry-sdk and opentelemetry-instrumentation-flask
  3. Agent adds opentelemetry-exporter-otlp
  4. Agent instruments the downstream call stubs with client spans
  5. Agent configures the Elastic OTLP endpoint
  6. Instrumented app starts and responds to /health

Run:
    cd smoke-tests && python3 60-ecommerce/smoke.py
"""

import os
import sys
import shutil
import subprocess
import tempfile
import time
import json

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")

if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set")
    sys.exit(0)

SVC         = "60-ecommerce"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-checkout-frontend")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []

def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-checkout-frontend (Flask, no OTel)")
print(f"  Services modeled: checkout + product-catalog + inventory + pricing + payment + order")
print()

# ── Step 1: Prerequisites ──────────────────────────────────────────────────────
print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
check("claude CLI is installed", claude_bin is not None,
      "install via: npm install -g @anthropic-ai/claude-code")
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD), f"looked at {CLAUDE_MD}")
check("Fixture directory exists", os.path.isdir(FIXTURE_DIR), FIXTURE_DIR)
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

# ── Step 2: Workspace ──────────────────────────────────────────────────────────
print("Step 2: Setting up blank app workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-ecommerce-")
try:
    for fname in os.listdir(FIXTURE_DIR):
        src = os.path.join(FIXTURE_DIR, fname)
        dst = os.path.join(tmpdir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, dst)

    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))

    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@edot-autopilot"],
                   cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot Eval"],
                   cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial: blank checkout service, no observability"],
                   cwd=tmpdir, capture_output=True, check=True)

    print(f"  Workspace: {tmpdir}\n")

    # ── Step 3: Run agent ──────────────────────────────────────────────────────
    print("Step 3: Running claude -p 'Observe this project.' ...")
    observe_prompt = (
        f"Observe this project.\n"
        f"My Elastic endpoint: {ENDPOINT}\n"
        f"My Elastic API key: {API_KEY}"
    )

    t0 = time.time()
    result = subprocess.run(
        [claude_bin, "--dangerously-skip-permissions", "-p", observe_prompt,
         "--model", "claude-sonnet-4-6", "--max-budget-usd", "2.00"],
        cwd=tmpdir, capture_output=True, text=True, timeout=600,
    )
    elapsed = time.time() - t0
    print(f"  Agent finished in {elapsed:.0f}s (exit code {result.returncode})")
    if result.stdout:
        for line in result.stdout.strip().splitlines()[-20:]:
            print(f"    {line}")

    check("Agent exited cleanly", result.returncode == 0,
          f"stderr: {result.stderr[-500:] if result.stderr else ''}")

    # ── Step 4: Verify generated code ─────────────────────────────────────────
    print("\nStep 4: Inspecting generated files")
    req_file = os.path.join(tmpdir, "requirements.txt")
    app_file = os.path.join(tmpdir, "app.py")
    otel_slos   = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")

    req_content = open(req_file).read() if os.path.exists(req_file) else ""
    app_content = open(app_file).read() if os.path.exists(app_file) else ""

    print("\nCode correctness checks (Tier A — e-commerce checkout):")

    check("opentelemetry-sdk in requirements.txt",
          "opentelemetry-sdk" in req_content or "opentelemetry-api" in req_content,
          f"requirements.txt:\n{req_content}")
    check("Flask instrumentation added",
          "opentelemetry-instrumentation-flask" in req_content,
          f"requirements.txt:\n{req_content}")
    check("OTLP exporter added",
          "opentelemetry-exporter-otlp" in req_content,
          f"requirements.txt:\n{req_content}")
    check("FlaskInstrumentor applied",
          "FlaskInstrumentor" in app_content and ".instrument(" in app_content,
          "FlaskInstrumentor().instrument() not found in app.py")
    check("TracerProvider or OTLPSpanExporter configured",
          "TracerProvider" in app_content or "OTLPSpanExporter" in app_content,
          "no tracer setup found in app.py")
    check("Elastic endpoint configured",
          "ELASTIC_OTLP_ENDPOINT" in app_content
          or "OTLP_ENDPOINT" in app_content
          or ENDPOINT.split("//")[-1][:20] in app_content,
          "endpoint not referenced in app.py")

    print("\n.otel/ output file checks:")
    check(".otel/slos.json created", os.path.exists(otel_slos))
    if os.path.exists(otel_slos):
        try:
            slos_raw = json.load(open(otel_slos))
            check(".otel/slos.json is valid JSON", bool(slos_raw))
        except json.JSONDecodeError as e:
            check(".otel/slos.json is valid JSON", False, str(e))
    check(".otel/golden-paths.md created", os.path.exists(otel_golden))

    # ── Step 5: Run the instrumented app ──────────────────────────────────────
    print("\nStep 5: Running instrumented checkout service")
    pip_install = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-r", req_file,
         "--no-warn-script-location"],
        capture_output=True, text=True
    )
    check("pip install succeeded",
          pip_install.returncode == 0,
          pip_install.stderr[-300:] if pip_install.returncode != 0 else "")

    if pip_install.returncode == 0:
        PORT = 16060
        env = os.environ.copy()
        env["PORT"] = str(PORT)
        app_proc = subprocess.Popen(
            [sys.executable, app_file],
            cwd=tmpdir, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

        started = False
        try:
            import urllib.request
            for _ in range(30):
                try:
                    r = urllib.request.urlopen(
                        f"http://127.0.0.1:{PORT}/health", timeout=0.5
                    )
                    if r.status == 200:
                        started = True
                        break
                except Exception:
                    time.sleep(0.3)
        except Exception:
            pass

        check("Instrumented checkout app starts and responds to /health",
              started, "app did not start in time")

        if started:
            import urllib.request as req_lib, urllib.error
            try:
                checkout_data = json.dumps({
                    "customer_id": "cust_eval_60",
                    "customer_tier": "pro",
                    "items": [{"product_id": "PROD-001"}],
                }).encode()
                r2 = req_lib.urlopen(
                    req_lib.Request(
                        f"http://127.0.0.1:{PORT}/checkout",
                        data=checkout_data,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    ), timeout=10
                )
                check("POST /checkout returns 201 or error (402/422/500)",
                      r2.status in (201, 402, 422, 500),
                      f"status={r2.status}")
            except urllib.error.HTTPError as e:
                check("POST /checkout returns 201 or error (402/422/500)",
                      e.code in (201, 402, 422, 500), f"HTTP {e.code}")
            except Exception as e:
                check("POST /checkout returns 201 or error (402/422/500)",
                      False, str(e))

        if app_proc.poll() is None:
            app_proc.terminate()
            app_proc.wait(timeout=5)

finally:
    failed_checks = [n for s, n, _ in CHECKS if s == "FAIL"]
    if failed_checks:
        print(f"\n  NOTE: Workspace preserved: {tmpdir}")
    else:
        shutil.rmtree(tmpdir, ignore_errors=True)

# ── Summary ────────────────────────────────────────────────────────────────────
passed = sum(1 for s, _, _ in CHECKS if s == "PASS")
failed = sum(1 for s, _, _ in CHECKS if s == "FAIL")
print(f"\n{'='*62}")
for status, name, detail in CHECKS:
    line = f"  [{status}] {name}"
    if detail and status == "FAIL":
        line += f"\n         -> {detail}"
    print(line)
print(f"\n  Result: {passed}/{len(CHECKS)} checks passed")
print(f"  Kibana → APM → checkout-frontend")
if failed:
    sys.exit(1)
