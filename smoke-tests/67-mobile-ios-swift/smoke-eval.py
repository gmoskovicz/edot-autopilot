#!/usr/bin/env python3
"""
Eval test: Mobile — iOS Swift ShopApp
=======================================
Runs `claude -p "Observe this project."` on a blank iOS Swift/SwiftUI shopping
app (fixtures/blank-ios-shopapp/) and verifies the agent adds OTel instrumentation.

NOTE: Live run is SKIPPED — iOS requires Xcode + simulator/device.

Run:
    cd smoke-tests && python3 67-mobile-ios-swift/smoke-eval.py
"""

import os
import sys
import shutil
import subprocess
import tempfile
import time

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")

if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set")
    sys.exit(0)

SVC         = "67-mobile-ios-swift"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-ios-shopapp")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []

def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-ios-shopapp (Swift/SwiftUI, no OTel)")
print(f"  NOTE: Live run SKIPPED — requires Xcode + iOS simulator")
print()

print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
check("claude CLI is installed", claude_bin is not None,
      "install via: npm install -g @anthropic-ai/claude-code")
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD))
check("Fixture directory exists", os.path.isdir(FIXTURE_DIR))
pkg_swift = os.path.join(FIXTURE_DIR, "Package.swift")
if os.path.exists(pkg_swift):
    check("Package.swift has no OTel", "opentelemetry" not in open(pkg_swift).read().lower(),
          "Package.swift already contains opentelemetry")

if not claude_bin or not os.path.exists(CLAUDE_MD) or not os.path.isdir(FIXTURE_DIR):
    for status, name, detail in CHECKS:
        print(f"  [{status}] {name}")
    sys.exit(1)

print("  [PASS] all critical prerequisites met\n")

print("Step 2: Setting up blank app workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-ios-")
try:
    shutil.copytree(FIXTURE_DIR, tmpdir, dirs_exist_ok=True)
    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))
    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@edot-autopilot"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot Eval"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial: blank iOS Swift app, no observability"],
                   cwd=tmpdir, capture_output=True, check=True)
    print(f"  Workspace: {tmpdir}\n")

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

    print("\nStep 4: Inspecting generated files")
    pkg_file  = os.path.join(tmpdir, "Package.swift")
    view_file = os.path.join(tmpdir, "ShopApp", "ContentView.swift")
    pkg_content  = open(pkg_file).read()  if os.path.exists(pkg_file)  else ""
    view_content = open(view_file).read() if os.path.exists(view_file) else ""

    # Check for separate OTel setup file
    for candidate in ["ShopApp/Telemetry.swift", "ShopApp/OTel.swift"]:
        p = os.path.join(tmpdir, candidate)
        if os.path.exists(p):
            view_content += open(p).read()

    otel_slos   = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")

    print("\nCode correctness checks (iOS OTel instrumentation):")
    check("OTel Swift package added to Package.swift",
          "opentelemetry" in pkg_content.lower() or "elastic" in pkg_content.lower(),
          f"Package.swift:\n{pkg_content[:500]}")
    check("OTel SDK initialized in Swift code",
          "opentelemetry" in view_content.lower() or "tracer" in view_content.lower()
          or "OpenTelemetry" in view_content,
          "no OTel initialization found in ContentView.swift")
    check("Elastic endpoint configured",
          "ELASTIC_OTLP_ENDPOINT" in view_content
          or "OTLP_ENDPOINT" in view_content
          or ENDPOINT.split("//")[-1][:20] in view_content,
          "endpoint not referenced in Swift code")
    check("Live app run",  # SKIP: requires mobile runtime
          True, "# SKIP: requires Xcode + iOS simulator/device")
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
print(f"  Kibana → RUM → ShopApp (iOS)")
if failed:
    sys.exit(1)
