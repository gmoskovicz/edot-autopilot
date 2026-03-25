#!/usr/bin/env python3
"""
Eval test: Tier A — Java Spring Boot
======================================
Runs `claude -p "Observe this project."` on a blank Spring Boot order API
(fixtures/blank-spring-orders/) and verifies the agent adds the correct
OpenTelemetry Java dependencies and configuration.

What this tests:
  1. Agent reads the blank Spring Boot app and understands it
  2. Agent adds io.opentelemetry:opentelemetry-sdk (or spring-boot-starter-otel)
  3. Agent adds the OTLP exporter dependency
  4. Agent adds OTel Java agent configuration (application.properties or ENV vars)
  5. Agent configures the Elastic endpoint
  6. (Optional) Compiles and runs if `mvn` / `java` available

Run:
    cd smoke-tests && python3 08-tier-a-java/smoke-eval.py

Requirements:
  - `claude` CLI installed and authenticated
  - ELASTIC_OTLP_ENDPOINT and ELASTIC_API_KEY set in .env or environment
  - `mvn` + `java` (optional — skips build if absent)
"""

import os
import sys
import json
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

SVC         = "08-tier-a-java"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-spring-orders")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []

def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-spring-orders (Spring Boot, no OTel)")
print(f"  Agent:   claude -p (non-interactive)")
print()

# ── Step 1: Prerequisites ──────────────────────────────────────────────────────
print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
java_bin   = shutil.which("java")
mvn_bin    = shutil.which("mvn")
check("claude CLI is installed", claude_bin is not None,
      "install via: npm install -g @anthropic-ai/claude-code")
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD), f"looked at {CLAUDE_MD}")
check("Fixture directory exists", os.path.isdir(FIXTURE_DIR), FIXTURE_DIR)
check("Fixture pom.xml has no OTel",
      "opentelemetry" not in open(os.path.join(FIXTURE_DIR, "pom.xml")).read(),
      "fixture pom.xml already contains opentelemetry — test is invalid")
check("java available (needed to build/run)",
      java_bin is not None,
      "java not found — build step will be skipped")
check("mvn available (needed to build)",
      mvn_bin is not None,
      "mvn not found — build step will be skipped")

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
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-java-")
try:
    shutil.copytree(FIXTURE_DIR, tmpdir, dirs_exist_ok=True)
    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))

    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@edot-autopilot"],
                   cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot Eval"],
                   cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial: blank Spring Boot app, no observability"],
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
        lines = result.stdout.strip().splitlines()
        for line in lines[-20:]:
            print(f"    {line}")

    check("Agent exited cleanly", result.returncode == 0,
          f"stderr: {result.stderr[-500:] if result.stderr else ''}")

    # ── Step 4: Verify generated code ─────────────────────────────────────────
    print("\nStep 4: Inspecting generated files")
    pom_file   = os.path.join(tmpdir, "pom.xml")
    pom_content = open(pom_file).read() if os.path.exists(pom_file) else ""

    # Also check for gradle
    build_gradle = os.path.join(tmpdir, "build.gradle")
    gradle_content = open(build_gradle).read() if os.path.exists(build_gradle) else ""
    build_content = pom_content + gradle_content

    # Check for application.properties or application.yml
    props_file = os.path.join(tmpdir, "src", "main", "resources", "application.properties")
    yml_file   = os.path.join(tmpdir, "src", "main", "resources", "application.yml")
    props_content  = open(props_file).read() if os.path.exists(props_file) else ""
    yml_content    = open(yml_file).read()   if os.path.exists(yml_file)   else ""
    config_content = props_content + yml_content

    otel_slos   = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")

    print("\nCode correctness checks (Tier A — Java auto-instrumentation):")

    check("OTel dependency added to build file",
          "opentelemetry" in build_content.lower(),
          "no opentelemetry dependency found in pom.xml or build.gradle")
    check("OTLP exporter or OTel agent configuration present",
          "otlp" in build_content.lower()
          or "otlp" in config_content.lower()
          or "opentelemetry.exporter" in config_content,
          "no OTLP exporter configuration found")
    check("Elastic endpoint configured",
          "ELASTIC_OTLP_ENDPOINT" in config_content
          or ENDPOINT.split("//")[-1][:20] in config_content
          or "OTLP_ENDPOINT" in config_content
          or "otel.exporter.otlp.endpoint" in config_content,
          "endpoint not referenced in config")

    print("\n.otel/ output file checks:")
    check(".otel/slos.json created", os.path.exists(otel_slos))
    check(".otel/golden-paths.md created", os.path.exists(otel_golden))

    # ── Step 5: Build (if mvn + java available) ────────────────────────────────
    if not mvn_bin or not java_bin:
        print("\nStep 5: SKIP — mvn/java not available")
        check("Maven build", True,
              "# SKIP: requires java + mvn — code checks above are sufficient")
    else:
        print("\nStep 5: Building with Maven (mvn package -DskipTests)...")
        build_result = subprocess.run(
            [mvn_bin, "package", "-DskipTests", "-q"],
            cwd=tmpdir, capture_output=True, text=True, timeout=300
        )
        check("mvn package succeeded",
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
print(f"  Kibana → APM → orders-service (Java Spring Boot)")
if failed:
    sys.exit(1)
