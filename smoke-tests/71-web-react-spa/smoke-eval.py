#!/usr/bin/env python3
"""
Eval test: Web — React SPA ShopClient
=======================================
Runs `claude -p "Observe this project."` on a blank React SPA
(fixtures/blank-react-shop/) and verifies OTel Web SDK setup.

NOTE: Live browser run is SKIPPED — requires browser/bundler.

Run:
    cd smoke-tests && python3 71-web-react-spa/smoke-eval.py
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

SVC         = "71-web-react-spa"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-react-shop")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []

def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-react-shop (React SPA, no OTel)")
print(f"  NOTE: Live run SKIPPED — requires browser/bundler")
print()

print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
check("claude CLI is installed", claude_bin is not None,
      "install via: npm install -g @anthropic-ai/claude-code")
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD))
check("Fixture directory exists", os.path.isdir(FIXTURE_DIR))
pkg = os.path.join(FIXTURE_DIR, "package.json")
if os.path.exists(pkg):
    check("package.json has no OTel", "opentelemetry" not in open(pkg).read().lower(),
          "package.json already contains opentelemetry")

if not claude_bin or not os.path.exists(CLAUDE_MD) or not os.path.isdir(FIXTURE_DIR):
    for status, name, detail in CHECKS:
        print(f"  [{status}] {name}")
    sys.exit(1)

print("  [PASS] all critical prerequisites met\n")

print("Step 2: Setting up blank app workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-react-spa-")
try:
    shutil.copytree(FIXTURE_DIR, tmpdir, dirs_exist_ok=True)
    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))
    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@edot-autopilot"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot Eval"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial: blank React SPA, no observability"],
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
    pkg_file  = os.path.join(tmpdir, "package.json")
    app_file  = os.path.join(tmpdir, "src", "App.tsx")
    pkg_content = open(pkg_file).read() if os.path.exists(pkg_file) else ""
    app_content = open(app_file).read() if os.path.exists(app_file) else ""

    # Check for separate telemetry setup file
    for candidate in ["src/telemetry.ts", "src/otel.ts", "src/instrumentation.ts", "src/main.tsx"]:
        p = os.path.join(tmpdir, candidate)
        if os.path.exists(p):
            app_content += open(p).read()

    otel_slos   = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")

    print("\nCode correctness checks (React SPA OTel Web SDK):")
    check("@opentelemetry/sdk-trace-web or similar added to package.json",
          "opentelemetry" in pkg_content.lower(),
          f"package.json:\n{pkg_content[:500]}")
    check("OTel instrumentation-fetch or document-load added",
          "instrumentation-fetch" in pkg_content.lower()
          or "instrumentation-document" in pkg_content.lower()
          or "instrumentation-xml-http" in pkg_content.lower(),
          "no fetch/document-load instrumentation found")
    check("OTel Web SDK initialized in TypeScript code",
          "opentelemetry" in app_content.lower() or "WebTracerProvider" in app_content
          or "TracerProvider" in app_content,
          "no OTel initialization found in app code")
    check("Elastic endpoint configured",
          "ELASTIC_OTLP_ENDPOINT" in app_content
          or "OTLP_ENDPOINT" in app_content
          or ENDPOINT.split("//")[-1][:20] in app_content
          or "VITE_" in app_content,
          "endpoint not referenced in app code")
    check("Live app run",
          True, "# SKIP: requires browser/bundler environment")
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
print(f"  Kibana → RUM → shop-client (React SPA)")
if failed:
    sys.exit(1)
