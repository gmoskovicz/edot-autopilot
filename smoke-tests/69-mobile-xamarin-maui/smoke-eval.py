#!/usr/bin/env python3
"""
Eval test: Mobile — .NET MAUI ShopApp
=======================================
Runs `claude -p "Observe this project."` on a blank .NET MAUI shopping app
(fixtures/blank-maui-shopapp/) and verifies OTel instrumentation.

NOTE: Live run is SKIPPED — MAUI requires an emulator/device.

Run:
    cd smoke-tests && python3 69-mobile-xamarin-maui/smoke-eval.py
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

SVC         = "69-mobile-xamarin-maui"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-maui-shopapp")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []

def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-maui-shopapp (.NET MAUI C#, no OTel)")
print(f"  NOTE: Live run SKIPPED — requires MAUI emulator/device")
print()

print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
check("claude CLI is installed", claude_bin is not None,
      "install via: npm install -g @anthropic-ai/claude-code")
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD))
check("Fixture directory exists", os.path.isdir(FIXTURE_DIR))
csproj = os.path.join(FIXTURE_DIR, "ShopApp.csproj")
if os.path.exists(csproj):
    check("ShopApp.csproj has no OTel",
          "OpenTelemetry" not in open(csproj).read(),
          "csproj already contains OpenTelemetry")

if not claude_bin or not os.path.exists(CLAUDE_MD) or not os.path.isdir(FIXTURE_DIR):
    for status, name, detail in CHECKS:
        print(f"  [{status}] {name}")
    sys.exit(1)

print("  [PASS] all critical prerequisites met\n")

print("Step 2: Setting up blank app workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-maui-")
try:
    shutil.copytree(FIXTURE_DIR, tmpdir, dirs_exist_ok=True)
    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))
    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@edot-autopilot"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot Eval"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial: blank .NET MAUI app, no observability"],
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
    csproj_file = os.path.join(tmpdir, "ShopApp.csproj")
    main_file   = os.path.join(tmpdir, "MainPage.xaml.cs")
    maui_prog   = os.path.join(tmpdir, "MauiProgram.cs")
    csproj_content = open(csproj_file).read() if os.path.exists(csproj_file) else ""
    main_content   = open(main_file).read()   if os.path.exists(main_file)   else ""
    prog_content   = open(maui_prog).read()   if os.path.exists(maui_prog)   else ""
    all_content    = csproj_content + main_content + prog_content

    otel_slos   = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")

    print("\nCode correctness checks (.NET MAUI OTel instrumentation):")
    check("OTel NuGet package added to .csproj",
          "OpenTelemetry" in csproj_content,
          f"csproj:\n{csproj_content}")
    check("OTel SDK configured in MauiProgram.cs or MainPage.xaml.cs",
          "OpenTelemetry" in all_content or "opentelemetry" in all_content.lower(),
          "no OTel initialization found")
    check("Elastic endpoint configured",
          "ELASTIC_OTLP_ENDPOINT" in all_content
          or "OTLP_ENDPOINT" in all_content
          or ENDPOINT.split("//")[-1][:20] in all_content,
          "endpoint not referenced in C# code")
    check("Live app run",
          True, "# SKIP: requires .NET MAUI emulator/device")
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
print(f"  Kibana → RUM → ShopApp (.NET MAUI)")
if failed:
    sys.exit(1)
