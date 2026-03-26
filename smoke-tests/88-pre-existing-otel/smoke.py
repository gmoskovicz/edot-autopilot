#!/usr/bin/env python3
"""
88-pre-existing-otel — Eval: Observe this project. (Augment existing OTel)
===========================================================================
Runs `claude -p "Observe this project."` on a Flask app that already has
partial OTel setup. Verifies the agent:
  1. Does NOT add a second TracerProvider (no duplicate provider)
  2. Upgrades deprecated semconv attribute names to 1.22+
  3. Adds business enrichment (order.value_usd, customer.tier, etc.)
  4. Adds record_exception to existing error paths
  5. App still runs correctly after modifications

This directly tests the gap: agents that blindly add a new TracerProvider
when one already exists create duplicate exporters and break tracing.

Run:
    cd smoke-tests && python3 88-pre-existing-otel/smoke.py
"""

import os
import sys
import time
import shutil
import subprocess
import tempfile

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")

if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set")
    sys.exit(0)

SVC         = "88-pre-existing-otel"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "partial-otel-app")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")

if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []
def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: partial-otel-app (Flask + partial OTel, needs augmentation)")
print(f"  Tests:   augment-not-replace, semconv upgrade, record_exception")
print()

# ── Step 1: Prerequisites ──────────────────────────────────────────────────────
print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
check("claude CLI is installed", claude_bin is not None,
      "install via: npm install -g @anthropic-ai/claude-code")
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD), f"looked at {CLAUDE_MD}")
check("Fixture app exists", os.path.isdir(FIXTURE_DIR))

fixture_app = os.path.join(FIXTURE_DIR, "app.py")
if os.path.exists(fixture_app):
    fixture_content = open(fixture_app).read()
    check("Fixture already has partial OTel (TracerProvider)",
          "TracerProvider" in fixture_content,
          "fixture should have an existing TracerProvider")
    check("Fixture has deprecated semconv attrs",
          "http.method" in fixture_content or "http.status_code" in fixture_content,
          "fixture should contain deprecated attribute names for agent to upgrade")

if any(s == "FAIL" for s, _, _ in CHECKS):
    print("Prerequisites failed — cannot continue")
    for status, name, detail in CHECKS:
        line = f"  [{status}] {name}"
        if detail and status == "FAIL":
            line += f"\n         -> {detail}"
        print(line)
    sys.exit(1)

print("  [PASS] all prerequisites met\n")

# ── Step 2: Temp workspace ─────────────────────────────────────────────────────
print("Step 2: Setting up partial-otel app workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-88-")
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
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot E2E"],
                   cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial: partial otel, needs augmentation"],
                   cwd=tmpdir, capture_output=True, check=True)

    check("Temp workspace created", True, tmpdir)
    print(f"  Workspace: {tmpdir}\n")

    # ── Step 3: Run claude ─────────────────────────────────────────────────────
    print("Step 3: Running claude -p 'Observe this project.' ...")
    observe_prompt = (
        f"Observe this project.\n"
        f"My Elastic endpoint: {ENDPOINT}\n"
        f"My Elastic API key: {API_KEY}"
    )

    t0 = time.time()
    result = subprocess.run(
        [claude_bin, "--dangerously-skip-permissions",
         "-p", observe_prompt,
         "--model", "claude-sonnet-4-6",
         "--max-budget-usd", "2.00"],
        cwd=tmpdir, capture_output=True, text=True, timeout=600,
    )
    elapsed = time.time() - t0

    print(f"  Agent finished in {elapsed:.0f}s (exit code {result.returncode})")
    if result.stdout:
        lines = result.stdout.strip().splitlines()
        print(f"  Agent output (last 10 lines of {len(lines)} total):")
        for line in lines[-10:]:
            print(f"    {line}")

    check("Agent exited cleanly", result.returncode == 0,
          f"stderr: {result.stderr[-500:] if result.stderr else ''}")

    # ── Step 4: Inspect diff ──────────────────────────────────────────────────
    print("\nStep 4: Inspecting what the agent changed")
    app_file    = os.path.join(tmpdir, "app.py")
    req_file    = os.path.join(tmpdir, "requirements.txt")
    app_content = open(app_file).read() if os.path.exists(app_file) else ""
    req_content = open(req_file).read() if os.path.exists(req_file) else ""

    print("\nAugment-not-replace checks:")
    provider_count = app_content.count("TracerProvider()")
    check("No duplicate TracerProvider added (count <= 1)",
          provider_count <= 1,
          f"found {provider_count} TracerProvider() calls in app.py — agent added a duplicate")

    check("Existing FlaskInstrumentor preserved",
          "FlaskInstrumentor" in app_content,
          "FlaskInstrumentor was removed — agent should augment, not replace")

    print("\nSemconv upgrade checks:")
    has_deprecated_method = "\"http.method\"" in app_content or "'http.method'" in app_content
    has_deprecated_status = "\"http.status_code\"" in app_content or "'http.status_code'" in app_content
    check("Deprecated http.method attribute removed/upgraded",
          not has_deprecated_method,
          "deprecated 'http.method' still present — should be 'http.request.method'")
    check("Deprecated http.status_code attribute removed/upgraded",
          not has_deprecated_status,
          "deprecated 'http.status_code' still present — should be 'http.response.status_code'")

    print("\nBusiness enrichment checks:")
    has_enrichment = any(attr in app_content for attr in [
        "order.value", "order_value", "amount_usd", "order.id", "order_id",
        "customer.tier", "customer_tier",
    ])
    check("Business span attributes added (order/customer)",
          has_enrichment,
          "no business enrichment attributes found in app.py")

    print("\nError handling checks:")
    has_record_exception = "record_exception" in app_content
    check("record_exception added to error paths",
          has_record_exception,
          "no record_exception call found — stack traces will be lost in Elastic APM")

    print("\nShutdown hygiene checks:")
    has_force_flush = "force_flush" in app_content
    check("force_flush added (atexit or lifespan)",
          has_force_flush,
          "no force_flush found — spans will be silently dropped on process exit")

    # ── Step 5: Run instrumented app ──────────────────────────────────────────
    print("\nStep 5: Running the augmented app")
    pip_install = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q",
         "-r", req_file, "--no-warn-script-location"],
        capture_output=True, text=True,
    )
    if pip_install.returncode != 0:
        check("pip install succeeded", False, pip_install.stderr[-500:])
    else:
        check("pip install succeeded", True)

    PORT = 15088
    env  = os.environ.copy()
    env["PORT"] = str(PORT)
    app_proc = subprocess.Popen(
        [sys.executable, app_file],
        cwd=tmpdir, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

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

    check("Augmented app starts and responds to /health", started)

    if started:
        print(f"  App running on port {PORT}")
        print("\nStep 6: Making test requests")

        r_order = http_lib.post(f"http://127.0.0.1:{PORT}/orders", json={
            "order_id": "ORD-AUGMENT-001",
            "customer_id": "CUST-001",
            "customer_tier": "premium",
            "amount_usd": 149.99,
        })
        check("POST /orders → 201",
              r_order.status_code == 201,
              f"status={r_order.status_code} body={r_order.text[:200]}")

        r_bad = http_lib.post(f"http://127.0.0.1:{PORT}/orders", json={
            "order_id": "ORD-BAD",
            "amount_usd": 0,
        })
        check("POST /orders with amount=0 → 400",
              r_bad.status_code == 400,
              f"status={r_bad.status_code}")

        print("\n  Waiting 3s for OTLP export to Elastic...")
        time.sleep(3)

        check("App stable after requests", app_proc.poll() is None,
              "app process died during requests")

    if 'app_proc' in dir() and app_proc.poll() is None:
        app_proc.terminate()
        app_proc.wait(timeout=5)

finally:
    failed_checks = [n for s, n, _ in CHECKS if s == "FAIL"]
    if failed_checks:
        print(f"\n  NOTE: Workspace preserved for inspection: {tmpdir}")
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
if failed:
    sys.exit(1)
