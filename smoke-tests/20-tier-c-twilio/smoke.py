#!/usr/bin/env python3
"""
E2E "Observe this project." — Tier C: Twilio SMS
=================================================
This test ACTUALLY runs `claude -p "Observe this project."` on a blank,
uninstrumented Python script that uses the Twilio SDK. It does not assume
or hardcode what the agent will generate.

What this tests:
  1. The agent reads the blank app and understands it (Twilio SDK, SMS sending)
  2. The agent correctly assigns Tier C (monkey-patch) because Twilio has no
     official OTel instrumentation library
  3. The agent wraps twilio.rest.Client.messages.create() with a CLIENT span
  4. The agent adds business enrichment (sms.to, sms.provider, sms.status)
  5. The generated requirements.txt includes the right OTel packages
  6. The instrumented script runs to completion without errors

Note: this is a script (not a web server), so there is no "run app + /health"
step. We verify code patterns instead.

Run:
    cd smoke-tests && python3 20-tier-c-twilio/smoke.py

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

SVC         = "20-tier-c-twilio"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-twilio-sms")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")

if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []
def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-twilio-sms (no OTel)")
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
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-20-")
try:
    for fname in os.listdir(FIXTURE_DIR):
        src = os.path.join(FIXTURE_DIR, fname)
        dst = os.path.join(tmpdir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, dst)

    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))

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

    req_file  = os.path.join(tmpdir, "requirements.txt")
    app_file  = os.path.join(tmpdir, "app.py")
    otel_slos = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")

    req_content = open(req_file).read() if os.path.exists(req_file) else ""
    app_content = open(app_file).read() if os.path.exists(app_file) else ""

    print("\nCode correctness checks (Tier C — monkey-patch):")

    # requirements.txt checks
    check("opentelemetry-sdk or opentelemetry-api added to requirements.txt",
          "opentelemetry-sdk" in req_content or "opentelemetry-api" in req_content,
          f"requirements.txt:\n{req_content}")
    check("twilio still in requirements.txt",
          "twilio" in req_content,
          f"requirements.txt:\n{req_content}")
    check("OTLP exporter added to requirements.txt",
          "opentelemetry-exporter-otlp" in req_content,
          f"requirements.txt:\n{req_content}")

    # app.py instrumentation checks — Tier C monkey-patch patterns
    print("\napp.py instrumentation checks (Tier C monkey-patch):")
    has_span_wrap = (
        "start_as_current_span" in app_content
        or "original_create" in app_content
        or "__wrapped__" in app_content
        or "messages.create" in app_content and "span" in app_content
    )
    check("Twilio messages.create wrapped in a span",
          has_span_wrap,
          "no start_as_current_span or monkey-patch pattern found in app.py")

    check("TracerProvider or OTLPSpanExporter configured",
          "TracerProvider" in app_content or "OTLPSpanExporter" in app_content,
          "no tracer setup found in app.py")

    check("Elastic endpoint configured from env",
          "ELASTIC_OTLP_ENDPOINT" in app_content or "OTLP_ENDPOINT" in app_content
          or (ENDPOINT.split("//")[1][:20] if "//" in ENDPOINT else ENDPOINT[:20]) in app_content,
          "endpoint not referenced in app.py")

    # Business enrichment checks
    print("\nBusiness enrichment checks:")
    has_sms_enrichment = any(
        attr in app_content for attr in [
            "sms.to", "sms.provider", "sms.status",
            "sms.from", "sms.message_sid",
        ]
    )
    check("SMS business span attributes added (sms.to, sms.provider, sms.status)",
          has_sms_enrichment,
          "no SMS business attributes found in app.py")

    has_span_kind_client = (
        "SpanKind.CLIENT" in app_content
        or "kind=SpanKind.CLIENT" in app_content
        or "CLIENT" in app_content
    )
    check("SpanKind.CLIENT used for outbound Twilio call",
          has_span_kind_client,
          "SpanKind.CLIENT not found — outbound calls should be CLIENT spans")

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
                      len(slos_raw) > 0, f"got empty list")
            else:
                check(".otel/slos.json is valid JSON with 'services' key",
                      "services" in slos_raw, f"keys: {list(slos_raw.keys())}")
        except json.JSONDecodeError as e:
            check(".otel/slos.json is valid JSON", False, str(e))

    check(".otel/golden-paths.md created",
          os.path.exists(otel_golden),
          f"expected at {otel_golden}")

    # ── Step 5: Run the instrumented script ───────────────────────────────────
    # This is a script, not a web server — we just run it and check exit code.
    print("\nStep 5: Running the instrumented script")

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

    env = os.environ.copy()
    env["ELASTIC_OTLP_ENDPOINT"] = ENDPOINT
    env["ELASTIC_API_KEY"]       = API_KEY

    script_result = subprocess.run(
        [sys.executable, app_file],
        cwd=tmpdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    check("Instrumented script runs to completion (exit 0)",
          script_result.returncode == 0,
          f"stderr: {script_result.stderr[-500:] if script_result.stderr else ''}"
          f"\nstdout: {script_result.stdout[-300:] if script_result.stdout else ''}")

    if script_result.returncode == 0:
        print(f"  Script ran successfully")
        if script_result.stdout:
            lines = script_result.stdout.strip().splitlines()
            for line in lines[-5:]:
                print(f"    {line}")

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
