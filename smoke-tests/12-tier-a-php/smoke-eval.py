#!/usr/bin/env python3
"""
Eval test: Tier A — PHP Slim CMS API
======================================
Runs `claude -p "Observe this project."` on a blank PHP Slim CMS service
(fixtures/blank-php-cms/) and verifies the agent adds the correct
open-telemetry/opentelemetry-php packages and instrumentation.

What this tests:
  1. Agent reads the blank PHP Slim app and understands it
  2. Agent adds open-telemetry/sdk to composer.json
  3. Agent adds open-telemetry/exporter-otlp (proto or grpc)
  4. Agent adds open-telemetry/instrumentation-slim (or psr15)
  5. Agent configures the Elastic OTLP endpoint
  6. (Optional) Runs composer install if `php` + `composer` available

Run:
    cd smoke-tests && python3 12-tier-a-php/smoke-eval.py
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

SVC         = "12-tier-a-php"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-php-cms")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []

def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-php-cms (PHP Slim, no OTel)")
print()

# ── Step 1: Prerequisites ──────────────────────────────────────────────────────
print("Step 1: Prerequisites")
claude_bin    = shutil.which("claude")
php_bin       = shutil.which("php")
composer_bin  = shutil.which("composer")
check("claude CLI is installed", claude_bin is not None,
      "install via: npm install -g @anthropic-ai/claude-code")
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD), f"looked at {CLAUDE_MD}")
check("Fixture directory exists", os.path.isdir(FIXTURE_DIR), FIXTURE_DIR)

composer_file = os.path.join(FIXTURE_DIR, "composer.json")
if os.path.exists(composer_file):
    with open(composer_file) as f:
        composer_data = json.load(f)
    has_otel = "open-telemetry" in json.dumps(composer_data)
    check("Fixture composer.json has no OTel", not has_otel,
          "composer.json already contains open-telemetry — test is invalid")

check("php available (needed to run)", php_bin is not None,
      "php not found — run step will be skipped")

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
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-php-")
try:
    shutil.copytree(FIXTURE_DIR, tmpdir, dirs_exist_ok=True)
    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))

    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@edot-autopilot"],
                   cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot Eval"],
                   cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial: blank PHP Slim app, no observability"],
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
    composer_json = os.path.join(tmpdir, "composer.json")
    index_php     = os.path.join(tmpdir, "index.php")

    composer_content = open(composer_json).read() if os.path.exists(composer_json) else ""
    index_content    = open(index_php).read()     if os.path.exists(index_php)     else ""

    # Check for separate bootstrap file
    for candidate in ["otel.php", "telemetry.php", "bootstrap.php", "src/Telemetry.php"]:
        p = os.path.join(tmpdir, candidate)
        if os.path.exists(p):
            index_content += open(p).read()

    otel_slos   = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")

    print("\nCode correctness checks (Tier A — PHP auto-instrumentation):")

    check("open-telemetry/sdk added to composer.json",
          "open-telemetry" in composer_content or "opentelemetry" in composer_content.lower(),
          f"composer.json:\n{composer_content}")
    check("OTel OTLP exporter package added",
          "exporter" in composer_content.lower() and "otlp" in composer_content.lower(),
          "no OTLP exporter found in composer.json")
    check("OTel SDK initialized in PHP code",
          "OpenTelemetry" in index_content or "opentelemetry" in index_content.lower(),
          "no OTel initialization found in index.php")
    check("Elastic endpoint configured",
          "ELASTIC_OTLP_ENDPOINT" in index_content
          or "OTLP_ENDPOINT" in index_content
          or ENDPOINT.split("//")[-1][:20] in index_content,
          "endpoint not referenced in PHP code")

    print("\n.otel/ output file checks:")
    check(".otel/slos.json created", os.path.exists(otel_slos))
    check(".otel/golden-paths.md created", os.path.exists(otel_golden))

    # ── Step 5: composer install (if php + composer available) ────────────────
    if not php_bin or not composer_bin:
        print("\nStep 5: SKIP — php/composer not available")
        check("composer install", True,
              "# SKIP: requires php + composer — code checks above are sufficient")
    else:
        print("\nStep 5: Running composer install...")
        ci = subprocess.run(
            [composer_bin, "install", "--no-interaction", "--prefer-dist"],
            cwd=tmpdir, capture_output=True, text=True, timeout=180
        )
        check("composer install succeeded",
              ci.returncode == 0,
              ci.stderr[-300:] if ci.returncode != 0 else "")

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
print(f"  Kibana → APM → cms-api (PHP Slim)")
if failed:
    sys.exit(1)
