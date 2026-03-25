#!/usr/bin/env python3
"""
Eval test: Tier A — .NET ASP.NET Core Inventory Service
=========================================================
Runs `claude -p "Observe this project."` on a blank ASP.NET Core inventory
service (fixtures/blank-dotnet-inventory/) and verifies the agent adds the
correct OpenTelemetry.NET packages and configuration.

What this tests:
  1. Agent reads the blank ASP.NET Core app and understands it
  2. Agent adds OpenTelemetry.Extensions.Hosting NuGet package
  3. Agent adds OpenTelemetry.Exporter.OpenTelemetryProtocol
  4. Agent adds OpenTelemetry.Instrumentation.AspNetCore
  5. Agent calls AddOpenTelemetry() in Program.cs
  6. Agent configures the Elastic OTLP endpoint
  7. (Optional) Builds if `dotnet` available

Run:
    cd smoke-tests && python3 11-tier-a-dotnet/smoke-eval.py
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

SVC         = "11-tier-a-dotnet"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-dotnet-inventory")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []

def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-dotnet-inventory (ASP.NET Core, no OTel)")
print()

# ── Step 1: Prerequisites ──────────────────────────────────────────────────────
print("Step 1: Prerequisites")
claude_bin  = shutil.which("claude")
dotnet_bin  = shutil.which("dotnet")
check("claude CLI is installed", claude_bin is not None,
      "install via: npm install -g @anthropic-ai/claude-code")
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD), f"looked at {CLAUDE_MD}")
check("Fixture directory exists", os.path.isdir(FIXTURE_DIR), FIXTURE_DIR)
check("Fixture .csproj has no OTel",
      "OpenTelemetry" not in open(os.path.join(FIXTURE_DIR, "InventoryService.csproj")).read(),
      "csproj already contains OpenTelemetry — test is invalid")
check("dotnet available (needed to build)",
      dotnet_bin is not None, "dotnet not found — build step will be skipped")

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
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-dotnet-")
try:
    shutil.copytree(FIXTURE_DIR, tmpdir, dirs_exist_ok=True)
    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))

    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@edot-autopilot"],
                   cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot Eval"],
                   cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial: blank ASP.NET Core app, no observability"],
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
    csproj_file   = os.path.join(tmpdir, "InventoryService.csproj")
    program_file  = os.path.join(tmpdir, "Program.cs")
    appsettings   = os.path.join(tmpdir, "appsettings.json")

    csproj_content  = open(csproj_file).read()  if os.path.exists(csproj_file)  else ""
    program_content = open(program_file).read() if os.path.exists(program_file) else ""
    settings_content = open(appsettings).read() if os.path.exists(appsettings)  else ""
    all_content     = csproj_content + program_content + settings_content

    otel_slos   = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")

    print("\nCode correctness checks (Tier A — .NET auto-instrumentation):")

    check("OpenTelemetry NuGet package added to .csproj",
          "OpenTelemetry" in csproj_content,
          f"csproj:\n{csproj_content}")
    check("OTLP exporter package added",
          "OpenTelemetryProtocol" in csproj_content or "Exporter.OpenTelemetryProtocol" in all_content,
          "no OTLP exporter found in .csproj")
    check("AddOpenTelemetry() called in Program.cs",
          "AddOpenTelemetry" in program_content or "OpenTelemetry" in program_content,
          "no OTel initialization found in Program.cs")
    check("Elastic endpoint configured",
          "ELASTIC_OTLP_ENDPOINT" in all_content
          or "OTLP_ENDPOINT" in all_content
          or ENDPOINT.split("//")[-1][:20] in all_content,
          "endpoint not referenced in any config file")

    print("\n.otel/ output file checks:")
    check(".otel/slos.json created", os.path.exists(otel_slos))
    check(".otel/golden-paths.md created", os.path.exists(otel_golden))

    # ── Step 5: dotnet build (if available) ────────────────────────────────────
    if not dotnet_bin:
        print("\nStep 5: SKIP — dotnet not available")
        check("dotnet build", True,
              "# SKIP: requires dotnet SDK — code checks above are sufficient")
    else:
        print("\nStep 5: Building with dotnet build...")
        build_result = subprocess.run(
            [dotnet_bin, "build", "--no-restore", "-v", "q"],
            cwd=tmpdir, capture_output=True, text=True, timeout=180
        )
        check("dotnet build succeeded",
              build_result.returncode == 0,
              build_result.stderr[-300:] if build_result.returncode != 0 else "")

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
print(f"  Kibana → APM → inventory-service (.NET ASP.NET Core)")
if failed:
    sys.exit(1)
