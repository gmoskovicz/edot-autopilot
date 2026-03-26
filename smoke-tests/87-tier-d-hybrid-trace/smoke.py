#!/usr/bin/env python3
"""
87-tier-d-hybrid-trace — Eval: Observe this project. (Tier A→D hybrid trace)
=============================================================================
Runs `claude -p "Observe this project."` on a Flask API that calls a shell
script subprocess. Verifies the agent:
  1. Instruments the Flask layer (Tier A)
  2. Adds sidecar calls to the shell script (Tier D)
  3. Passes `traceparent` from the Flask span to the shell script so both
     spans share the same trace_id in Elastic (the orphan span problem)

This directly tests the most common Tier D failure: spans from legacy
components appearing as isolated orphan traces instead of connected children.

Run:
    cd smoke-tests && python3 87-tier-d-hybrid-trace/smoke.py
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

SVC         = "87-tier-d-hybrid-trace"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-hybrid-app")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")

if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []
def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-hybrid-app (Flask API + shell script, no OTel)")
print(f"  Tests:   traceparent propagation A→D (orphan span prevention)")
print()

# ── Step 1: Prerequisites ──────────────────────────────────────────────────────
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
), "fixture already contains opentelemetry")

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
print("Step 2: Setting up blank app workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-87-")
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
    subprocess.run(["git", "commit", "-m", "initial: blank app, no observability"],
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

    req_file    = os.path.join(tmpdir, "requirements.txt")
    app_file    = os.path.join(tmpdir, "app.py")
    script_file = os.path.join(tmpdir, "archive.sh")
    req_content = open(req_file).read() if os.path.exists(req_file) else ""
    app_content = open(app_file).read() if os.path.exists(app_file) else ""
    sh_content  = open(script_file).read() if os.path.exists(script_file) else ""

    print("\nTier A checks (Flask layer):")
    check("opentelemetry packages added to requirements.txt",
          "opentelemetry" in req_content,
          f"requirements.txt:\n{req_content}")
    check("FlaskInstrumentor or start_as_current_span in app.py",
          "FlaskInstrumentor" in app_content or "start_as_current_span" in app_content,
          "no OTel instrumentation found in app.py")
    check("ELASTIC_OTLP_ENDPOINT referenced in app.py",
          "ELASTIC_OTLP_ENDPOINT" in app_content,
          "endpoint not referenced in app.py")

    print("\nTier D checks (shell script + traceparent propagation):")
    has_sidecar_call = "9411" in sh_content or "curl" in sh_content or "SIDECAR" in sh_content
    check("Sidecar call added to archive.sh",
          has_sidecar_call,
          f"no sidecar HTTP call found in archive.sh:\n{sh_content[:500]}")

    has_traceparent = (
        "traceparent" in sh_content.lower() or
        "TRACEPARENT" in sh_content or
        "W3C" in sh_content
    )
    check("traceparent forwarded in archive.sh (orphan span prevention)",
          has_traceparent,
          "archive.sh does not pass traceparent to sidecar — spans will be orphaned")

    has_flask_propagation = (
        "traceparent" in app_content.lower() or
        "inject" in app_content or
        "propagat" in app_content.lower() or
        "TRACEPARENT" in app_content
    )
    check("Flask app propagates traceparent to subprocess",
          has_flask_propagation,
          "app.py does not inject traceparent into subprocess env")

    print("\nBusiness enrichment checks:")
    has_enrichment = any(attr in app_content for attr in [
        "order.id", "order_id", "amount_usd", "customer.id", "customer_id",
    ])
    check("Business span attributes added", has_enrichment,
          "no business attributes found in app.py")

    # ── Step 5: Run instrumented app ──────────────────────────────────────────
    print("\nStep 5: Running the instrumented app")
    pip_install = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q",
         "-r", req_file, "--no-warn-script-location"],
        capture_output=True, text=True,
    )
    if pip_install.returncode != 0:
        check("pip install succeeded", False, pip_install.stderr[-500:])
    else:
        check("pip install succeeded", True)

    PORT = 15087
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

    check("Instrumented app starts and responds to /health", started)

    if started:
        print(f"  App running on port {PORT}")
        print("\nStep 6: Making test requests")

        r_order = http_lib.post(f"http://127.0.0.1:{PORT}/orders", json={
            "order_id": "ORD-HYBRID-001",
            "customer_id": "CUST-001",
            "amount_usd": 299.99,
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
