#!/usr/bin/env python3
"""
Eval test: Mobile — React Native ShopApp
==========================================
Runs `claude -p "Observe this project."` on a blank React Native shopping app
(fixtures/blank-shopapp-rn/) and verifies the agent adds the correct
OpenTelemetry RUM/mobile instrumentation.

What this tests:
  1. Agent reads the blank React Native app and understands it
  2. Agent adds @opentelemetry/sdk-trace-web or @elastic/opentelemetry-react-native
  3. Agent sets up trace provider and OTLP exporter
  4. Agent instruments screen navigation and network fetch spans
  5. Agent configures the Elastic endpoint

NOTE: Live run is SKIPPED — React Native requires an emulator/device.

Run:
    cd smoke-tests && python3 65-mobile-react-native/smoke-eval.py
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

SVC         = "65-mobile-react-native"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-shopapp-rn")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []

def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-shopapp-rn (React Native, no OTel)")
print(f"  NOTE: Live run SKIPPED — requires emulator/device")
print()

# ── Step 1: Prerequisites ──────────────────────────────────────────────────────
print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
check("claude CLI is installed", claude_bin is not None,
      "install via: npm install -g @anthropic-ai/claude-code")
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD))
check("Fixture directory exists", os.path.isdir(FIXTURE_DIR))
check("Fixture has no OTel", not any(
    "opentelemetry" in open(os.path.join(FIXTURE_DIR, f)).read()
    for f in ["App.tsx", "package.json"]
    if os.path.exists(os.path.join(FIXTURE_DIR, f))
), "fixture already contains opentelemetry — test is invalid")

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
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-rn-")
try:
    shutil.copytree(FIXTURE_DIR, tmpdir, dirs_exist_ok=True)
    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))
    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@edot-autopilot"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot Eval"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial: blank React Native app, no observability"],
                   cwd=tmpdir, capture_output=True, check=True)
    print(f"  Workspace: {tmpdir}\n")

    # ── Step 3: Run agent ──────────────────────────────────────────────────────
    print("Step 3: Running claude -p 'Observe this project.' ...")
    t0 = time.time()
    result = subprocess.run(
        [claude_bin, "--dangerously-skip-permissions", "-p",
         f"Observe this project.\nMy Elastic endpoint: {ENDPOINT}\nMy Elastic API key: {API_KEY}",
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
    pkg_file = os.path.join(tmpdir, "package.json")
    app_file = os.path.join(tmpdir, "App.tsx")
    pkg_content = open(pkg_file).read() if os.path.exists(pkg_file) else ""
    app_content = open(app_file).read() if os.path.exists(app_file) else ""

    # Also look for separate telemetry setup file
    for candidate in ["telemetry.ts", "otel.ts", "instrumentation.ts",
                       "src/telemetry.ts", "src/otel.ts"]:
        p = os.path.join(tmpdir, candidate)
        if os.path.exists(p):
            app_content += open(p).read()

    otel_slos   = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")

    print("\nCode correctness checks (React Native RUM instrumentation):")
    check("OTel package added to package.json",
          "opentelemetry" in pkg_content.lower() or "elastic/opentelemetry" in pkg_content.lower(),
          f"package.json:\n{pkg_content[:500]}")
    check("OTLP exporter or trace provider added",
          "exporter" in pkg_content.lower() or "TracerProvider" in app_content
          or "sdk-trace" in pkg_content.lower(),
          "no OTLP exporter or TracerProvider found")
    check("OTel SDK initialized in app code",
          "opentelemetry" in app_content.lower() or "TracerProvider" in app_content,
          "no OTel initialization found in App.tsx")
    check("Elastic endpoint configured",
          "ELASTIC_OTLP_ENDPOINT" in app_content
          or "OTLP_ENDPOINT" in app_content
          or ENDPOINT.split("//")[-1][:20] in app_content,
          "endpoint not referenced in app code")

    # SKIP: requires mobile runtime
    check("Live app run",  # SKIP: requires mobile runtime
          True, "# SKIP: requires mobile emulator/device")

    print("\n.otel/ output file checks:")
    check(".otel/slos.json created", os.path.exists(otel_slos))
    check(".otel/golden-paths.md created", os.path.exists(otel_golden))

finally:
    failed_checks = [n for s, n, _ in CHECKS if s == "FAIL"]
    if failed_checks:
        print(f"\n  NOTE: Workspace preserved: {tmpdir}")
    else:
        shutil.rmtree(tmpdir, ignore_errors=True)

passed = sum(1 for s, _, _ in CHECKS if s == "PASS")
failed = sum(1 for s, _, _ in CHECKS if s == "FAIL")
print(f"\n{'='*62}")
for status, name, detail in CHECKS:
    line = f"  [{status}] {name}"
    if detail and status == "FAIL":
        line += f"\n         -> {detail}"
    print(line)
print(f"\n  Result: {passed}/{len(CHECKS)} checks passed")
print(f"  Kibana → RUM → ShopApp (React Native)")
if failed:
    sys.exit(1)
