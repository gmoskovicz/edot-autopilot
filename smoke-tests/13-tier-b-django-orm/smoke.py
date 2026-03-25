#!/usr/bin/env python3
"""
EVAL TEST: Tier B — Django ORM Inventory Reorder (Real Agent Invocation)
=========================================================================
*** EVAL TEST — runs `claude -p` and costs ~$1-2 per execution ***

This test ACTUALLY runs `claude -p "Observe this project."` on a blank,
uninstrumented Django management command app. It does not assume or hardcode
what the agent will generate.

What this tests:
  1. The agent reads the blank app and understands it (Django management command
     outside the request/response cycle — no auto-instrumentation fires)
  2. The agent correctly assigns Tier B (manual ORM wrapping)
  3. The agent wraps `Product.objects.filter` and `PurchaseOrder.objects_create`
     with explicit CLIENT spans
  4. The outer `handle_reorders` function gets a SERVER span
  5. Business enrichment: po.product_sku, po.quantity, po.value_usd,
     inventory.products_below_threshold
  6. The instrumented command runs end-to-end

Run:
    cd smoke-tests && python3 13-tier-b-django-orm/smoke.py

Requirements (in addition to requirements.txt):
  - `claude` CLI installed and authenticated
  - ELASTIC_OTLP_ENDPOINT and ELASTIC_API_KEY set in .env or environment
"""

import os
import sys
import time
import shutil
import subprocess
import tempfile
import json

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")

if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set")
    sys.exit(0)

SVC = "13-eval-tier-b-django-orm"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-django-inventory")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")

if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []
def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  *** EVAL TEST — invokes claude -p (costs ~$1-2) ***")
print(f"  Fixture: blank-django-inventory (no OTel)")
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
tmpdir = tempfile.mkdtemp(prefix="edot-eval-13-")
try:
    for fname in os.listdir(FIXTURE_DIR):
        src = os.path.join(FIXTURE_DIR, fname)
        dst = os.path.join(tmpdir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, dst)

    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))

    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@edot-autopilot"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot Eval"], cwd=tmpdir, capture_output=True)
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
        timeout=600,
    )
    elapsed = time.time() - t0

    print(f"  Agent finished in {elapsed:.0f}s (exit code {result.returncode})")
    if result.stdout:
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

    new_files_result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=tmpdir, capture_output=True, text=True
    )
    new_files = [f.strip() for f in new_files_result.stdout.splitlines() if f.strip()]

    print(f"  Modified files (git diff): {len(diff.splitlines())} diff lines")
    print(f"  New files: {new_files}")

    req_file = os.path.join(tmpdir, "requirements.txt")
    app_file = os.path.join(tmpdir, "app.py")
    otel_slos = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")

    req_content = open(req_file).read() if os.path.exists(req_file) else ""
    app_content = open(app_file).read() if os.path.exists(app_file) else ""

    print("\nCode correctness checks (Tier B — manual ORM wrapping):")

    # requirements.txt checks
    check("opentelemetry-sdk or opentelemetry-api added to requirements.txt",
          "opentelemetry-sdk" in req_content or "opentelemetry-api" in req_content,
          f"requirements.txt:\n{req_content}")
    check("OTLP exporter added",
          "opentelemetry-exporter-otlp" in req_content,
          f"requirements.txt:\n{req_content}")

    # app.py Tier B pattern checks
    check("Manual span creation present (tracer.start_as_current_span)",
          "start_as_current_span" in app_content,
          "no manual span creation found in app.py")
    check("ORM filter wrapped with CLIENT span",
          ("django.orm.filter" in app_content or "orm.filter" in app_content
           or ("filter" in app_content and "SpanKind.CLIENT" in app_content)),
          "no CLIENT span wrapping ORM filter found in app.py")
    check("ORM save/create wrapped with CLIENT span",
          ("django.orm.save" in app_content or "orm.save" in app_content
           or "orm.create" in app_content
           or ("save" in app_content and "SpanKind.CLIENT" in app_content)
           or ("create" in app_content and "SpanKind.CLIENT" in app_content)),
          "no CLIENT span wrapping ORM save/create found in app.py")
    check("Outer handle_reorders wrapped with SERVER span",
          ("handle_reorders" in app_content
           and ("SpanKind.SERVER" in app_content or "SERVER" in app_content)),
          "handle_reorders SERVER span not found in app.py")
    check("Elastic endpoint configured from env",
          "ELASTIC_OTLP_ENDPOINT" in app_content or "OTLP_ENDPOINT" in app_content
          or ENDPOINT.split("//")[1][:20] in app_content,
          "endpoint not referenced in app.py")

    # Business enrichment checks
    print("\nBusiness enrichment checks:")
    has_inventory_enrichment = any(
        attr in app_content for attr in [
            "po.product_sku", "po.quantity", "po.value", "po_value",
            "reorder.quantity", "reorder_qty", "reorder.total_value",
            "inventory.products_below_threshold", "supplier.id",
        ]
    )
    check("Business span attributes added (PO/inventory/supplier)",
          has_inventory_enrichment,
          "no inventory/PO business enrichment attributes found in app.py")

    # .otel/ output files
    print("\n.otel/ output file checks:")
    check(".otel/slos.json created",
          os.path.exists(otel_slos),
          f"expected at {otel_slos}")
    if os.path.exists(otel_slos):
        try:
            slos_raw = json.load(open(otel_slos))
            if isinstance(slos_raw, list):
                check(".otel/slos.json is valid JSON with at least one SLO",
                      len(slos_raw) > 0, "got empty list")
            else:
                check(".otel/slos.json is valid JSON with 'services' key",
                      "services" in slos_raw,
                      f"keys: {list(slos_raw.keys())}")
        except json.JSONDecodeError as e:
            check(".otel/slos.json is valid JSON", False, str(e))

    check(".otel/golden-paths.md created",
          os.path.exists(otel_golden),
          f"expected at {otel_golden}")

    # ── Step 5: Run the instrumented command ──────────────────────────────────
    print("\nStep 5: Running the instrumented management command")

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

    run_result = subprocess.run(
        [sys.executable, app_file],
        cwd=tmpdir,
        capture_output=True,
        text=True,
        timeout=60,
    )
    check("Instrumented command runs without error",
          run_result.returncode == 0,
          f"returncode={run_result.returncode}\n"
          f"stdout: {run_result.stdout[-300:]}\n"
          f"stderr: {run_result.stderr[-300:]}")

    if run_result.returncode == 0:
        check("Command output mentions purchase orders",
              "PO-" in run_result.stdout or "purchase order" in run_result.stdout.lower(),
              f"stdout: {run_result.stdout[:300]}")

        print("\n  Waiting 3s for OTLP export to Elastic...")
        time.sleep(3)

finally:
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
