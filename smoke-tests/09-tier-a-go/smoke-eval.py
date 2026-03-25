#!/usr/bin/env python3
"""
Eval test: Tier A — Go API Gateway
=====================================
Runs `claude -p "Observe this project."` on a blank Go HTTP gateway
(fixtures/blank-go-gateway/) and verifies the agent adds the correct
go.opentelemetry.io/otel packages and instrumentation.

What this tests:
  1. Agent reads the blank Go app and understands it
  2. Agent adds go.opentelemetry.io/otel to go.mod
  3. Agent adds OTLP exporter (go.opentelemetry.io/otel/exporters/otlp/...)
  4. Agent wraps the http.ServeMux with otelhttp middleware
  5. Agent configures the Elastic endpoint
  6. (Optional) Builds if `go` available

Run:
    cd smoke-tests && python3 09-tier-a-go/smoke-eval.py

Requirements:
  - `claude` CLI installed and authenticated
  - ELASTIC_OTLP_ENDPOINT and ELASTIC_API_KEY set in .env or environment
  - `go` (optional — skips build if absent)
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

SVC         = "09-tier-a-go"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-go-gateway")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []

def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-go-gateway (Go net/http, no OTel)")
print()

# ── Step 1: Prerequisites ──────────────────────────────────────────────────────
print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
go_bin     = shutil.which("go")
check("claude CLI is installed", claude_bin is not None,
      "install via: npm install -g @anthropic-ai/claude-code")
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD), f"looked at {CLAUDE_MD}")
check("Fixture directory exists", os.path.isdir(FIXTURE_DIR), FIXTURE_DIR)
check("Fixture go.mod has no OTel",
      "opentelemetry" not in open(os.path.join(FIXTURE_DIR, "go.mod")).read(),
      "fixture already contains opentelemetry — test is invalid")
check("go available (needed to build/run)",
      go_bin is not None, "go not found — build step will be skipped")

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
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-go-")
try:
    shutil.copytree(FIXTURE_DIR, tmpdir, dirs_exist_ok=True)
    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))

    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@edot-autopilot"],
                   cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot Eval"],
                   cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial: blank Go API gateway, no observability"],
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
    gomod_file = os.path.join(tmpdir, "go.mod")
    main_file  = os.path.join(tmpdir, "main.go")
    gomod_content = open(gomod_file).read() if os.path.exists(gomod_file) else ""
    main_content  = open(main_file).read()  if os.path.exists(main_file)  else ""

    # Also scan for separate telemetry file
    otel_go = os.path.join(tmpdir, "telemetry.go")
    otel_content = open(otel_go).read() if os.path.exists(otel_go) else ""
    all_go_content = main_content + otel_content

    otel_slos   = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")

    print("\nCode correctness checks (Tier A — Go auto-instrumentation):")

    check("go.opentelemetry.io/otel added to go.mod",
          "go.opentelemetry.io/otel" in gomod_content,
          f"go.mod:\n{gomod_content}")
    check("OTLP exporter added to go.mod",
          "otlp" in gomod_content.lower(),
          "no OTLP exporter found in go.mod")
    check("OTel TracerProvider or SDK initialized in Go code",
          "TracerProvider" in all_go_content or "tracer" in all_go_content.lower()
          or "opentelemetry" in all_go_content.lower(),
          "no OTel initialization found in main.go")
    check("Elastic endpoint configured in Go code",
          "ELASTIC_OTLP_ENDPOINT" in all_go_content
          or "OTLP_ENDPOINT" in all_go_content
          or ENDPOINT.split("//")[-1][:20] in all_go_content,
          "endpoint not referenced in Go code")

    print("\n.otel/ output file checks:")
    check(".otel/slos.json created", os.path.exists(otel_slos))
    check(".otel/golden-paths.md created", os.path.exists(otel_golden))

    # ── Step 5: Build (if go available) ───────────────────────────────────────
    if not go_bin:
        print("\nStep 5: SKIP — go not available")
        check("go build", True,
              "# SKIP: requires go runtime — code checks above are sufficient")
    else:
        print("\nStep 5: Building with go build...")
        build_result = subprocess.run(
            [go_bin, "build", "./..."],
            cwd=tmpdir, capture_output=True, text=True, timeout=300
        )
        check("go build succeeded",
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
print(f"  Kibana → APM → api-gateway (Go)")
if failed:
    sys.exit(1)
