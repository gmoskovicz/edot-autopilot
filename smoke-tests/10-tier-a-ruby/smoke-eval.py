#!/usr/bin/env python3
"""
Eval test: Tier A — Ruby Sinatra Subscriptions
================================================
Runs `claude -p "Observe this project."` on a blank Sinatra subscription
service (fixtures/blank-sinatra-subscriptions/) and verifies the agent adds
the correct opentelemetry-ruby gems and instrumentation.

What this tests:
  1. Agent reads the blank Sinatra app and understands it
  2. Agent adds opentelemetry-sdk and opentelemetry-exporter-otlp gems
  3. Agent adds opentelemetry-instrumentation-sinatra (or rack)
  4. Agent configures the Elastic OTLP endpoint
  5. (Optional) Runs bundle install if `ruby` + `bundler` available

Run:
    cd smoke-tests && python3 10-tier-a-ruby/smoke-eval.py
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

SVC         = "10-tier-a-ruby"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-sinatra-subscriptions")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []

def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-sinatra-subscriptions (Ruby, no OTel)")
print()

# ── Step 1: Prerequisites ──────────────────────────────────────────────────────
print("Step 1: Prerequisites")
claude_bin  = shutil.which("claude")
ruby_bin    = shutil.which("ruby")
bundle_bin  = shutil.which("bundle")
check("claude CLI is installed", claude_bin is not None,
      "install via: npm install -g @anthropic-ai/claude-code")
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD), f"looked at {CLAUDE_MD}")
check("Fixture directory exists", os.path.isdir(FIXTURE_DIR), FIXTURE_DIR)
check("Fixture Gemfile has no OTel",
      "opentelemetry" not in open(os.path.join(FIXTURE_DIR, "Gemfile")).read(),
      "Gemfile already contains opentelemetry — test is invalid")
check("ruby available (needed to run)", ruby_bin is not None,
      "ruby not found — run step will be skipped")

if not claude_bin or not os.path.exists(CLAUDE_MD) or not os.path.isdir(FIXTURE_DIR):
    print("Critical prerequisites failed — cannot continue")
    for status, name, detail in CHECKS:
        line = f"  [{status}] {name}"
        if detail and status == "FAIL":
            line += f"\n         -> {detail}"
        print(line)
    sys.exit(1)

print("  [PASS] all critical prerequisites met\n")

# ── Step 2: Workspace ──────────────────────────────────────────────────────────
print("Step 2: Setting up blank app workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-ruby-")
try:
    shutil.copytree(FIXTURE_DIR, tmpdir, dirs_exist_ok=True)
    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))

    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@edot-autopilot"],
                   cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot Eval"],
                   cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial: blank Sinatra app, no observability"],
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
    gemfile_file = os.path.join(tmpdir, "Gemfile")
    app_file     = os.path.join(tmpdir, "app.rb")
    gemfile_content = open(gemfile_file).read() if os.path.exists(gemfile_file) else ""
    app_content     = open(app_file).read()     if os.path.exists(app_file)     else ""

    # Also look for separate telemetry initializer
    for candidate in ["otel.rb", "telemetry.rb", "instrumentation.rb", "config/otel.rb"]:
        p = os.path.join(tmpdir, candidate)
        if os.path.exists(p):
            app_content += open(p).read()

    otel_slos   = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")

    print("\nCode correctness checks (Tier A — Ruby auto-instrumentation):")

    check("opentelemetry-sdk gem added to Gemfile",
          "opentelemetry-sdk" in gemfile_content,
          f"Gemfile:\n{gemfile_content}")
    check("opentelemetry-exporter-otlp gem added to Gemfile",
          "opentelemetry-exporter-otlp" in gemfile_content,
          f"Gemfile:\n{gemfile_content}")
    check("OTel instrumentation gem added (sinatra or rack or all)",
          "opentelemetry-instrumentation" in gemfile_content,
          "no opentelemetry-instrumentation-* gem found in Gemfile")
    check("OTel SDK configured in Ruby code",
          "OpenTelemetry" in app_content or "opentelemetry" in app_content.lower(),
          "no OTel initialization found in app.rb")
    check("Elastic endpoint configured",
          "ELASTIC_OTLP_ENDPOINT" in app_content
          or "OTLP_ENDPOINT" in app_content
          or ENDPOINT.split("//")[-1][:20] in app_content,
          "endpoint not referenced in Ruby code")

    print("\n.otel/ output file checks:")
    check(".otel/slos.json created", os.path.exists(otel_slos))
    check(".otel/golden-paths.md created", os.path.exists(otel_golden))

    # ── Step 5: bundle install (if ruby + bundle available) ────────────────────
    if not ruby_bin or not bundle_bin:
        print("\nStep 5: SKIP — ruby/bundler not available")
        check("bundle install", True,
              "# SKIP: requires ruby + bundler — code checks above are sufficient")
    else:
        print("\nStep 5: Running bundle install...")
        bi = subprocess.run(
            [bundle_bin, "install", "--jobs=4"],
            cwd=tmpdir, capture_output=True, text=True, timeout=180
        )
        check("bundle install succeeded",
              bi.returncode == 0,
              bi.stderr[-300:] if bi.returncode != 0 else "")

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
print(f"  Kibana → APM → subscription-service (Ruby Sinatra)")
if failed:
    sys.exit(1)
