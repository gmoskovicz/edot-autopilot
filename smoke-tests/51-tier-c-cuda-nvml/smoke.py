#!/usr/bin/env python3
"""
E2E "Observe this project." — Tier C: CUDA / NVIDIA NVML (pynvml)
==================================================================
Runs `claude -p "Observe this project."` on a blank LLM inference service
that calls pynvml directly for GPU monitoring but has no OTel instrumentation.

EDOT Autopilot workflow:
  1. Reads blank fixture — finds pynvml calls + inference loop, no OTel
  2. Assigns Tier C: adds per-request trace spans + hw.gpu.* metric collection
  3. Wraps inference function with SpanKind.SERVER root spans
  4. Adds OTel hw.gpu.* metrics: utilization, memory usage, temperature, power

Expected agent output:
  - Traces: cuda.inference_request (SERVER) with child kernel spans
  - Metrics: hw.gpu.utilization, hw.gpu.memory.usage, hw.gpu.memory.utilization
  - Logs: structured inference events correlated to spans

Run:
    cd smoke-tests && python3 51-tier-c-cuda-nvml/smoke.py
"""

import os
import sys
import time
import shutil
import subprocess
import tempfile

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")
if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set")
    sys.exit(0)

SVC         = "51-tier-c-cuda-nvml"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-cuda-nvml")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")

if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []
def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-cuda-nvml (no OTel)")
print(f"  Agent:   claude -p (non-interactive)")
print()

# ── Step 1: Verify prerequisites ──────────────────────────────────────────────
print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
check("claude CLI is installed", claude_bin is not None,
      "install via: npm install -g @anthropic-ai/claude-code")
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD), f"looked at {CLAUDE_MD}")
check("Fixture dir exists", os.path.isdir(FIXTURE_DIR), FIXTURE_DIR)
check("Fixture has no OTel", not any(
    "opentelemetry" in open(os.path.join(FIXTURE_DIR, f)).read()
    for f in ["app.py", "requirements.txt"]
    if os.path.exists(os.path.join(FIXTURE_DIR, f))
), "fixture already contains opentelemetry — test is invalid")

if any(s == "FAIL" for s, _, _ in CHECKS):
    for status, name, detail in CHECKS:
        line = f"  [{status}] {name}"
        if detail and status == "FAIL":
            line += f"\n         -> {detail}"
        print(line)
    sys.exit(1)
print("  [PASS] all prerequisites met\n")

# ── Step 2: Set up temp workspace ─────────────────────────────────────────────
print("Step 2: Setting up blank app workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-cuda-nvml-")
try:
    for fname in os.listdir(FIXTURE_DIR):
        src = os.path.join(FIXTURE_DIR, fname)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(tmpdir, fname))

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

    # ── Step 4: Inspect what the agent changed ────────────────────────────────
    print("\nStep 4: Inspecting what the agent changed")
    new_files_result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=tmpdir, capture_output=True, text=True
    )
    new_files = [f.strip() for f in new_files_result.stdout.splitlines() if f.strip()]
    print(f"  New files: {new_files}")

    app_file = os.path.join(tmpdir, "app.py")
    req_file = os.path.join(tmpdir, "requirements.txt")
    app_content = open(app_file).read() if os.path.exists(app_file) else ""
    req_content = open(req_file).read() if os.path.exists(req_file) else ""

    print("\nTier C GPU instrumentation checks:")
    check("opentelemetry added to requirements.txt",
          "opentelemetry" in req_content,
          f"requirements.txt:\n{req_content}")
    check("Inference request wrapped in a span",
          "start_as_current_span" in app_content or "start_span" in app_content,
          "no OTel span context manager found in app.py")
    check("GPU metric collection added",
          any(metric in app_content for metric in [
              "hw.gpu.utilization", "hw.gpu.memory", "gpu.utilization",
              "create_gauge", "create_counter", "create_histogram",
          ]),
          "no GPU metric instruments found in app.py")
    check("NVML data recorded as OTel metrics or span attributes",
          any(attr in app_content for attr in [
              "nvmlDeviceGetUtilizationRates", "nvmlDeviceGetMemoryInfo",
              "gpu.utilization", "hw.gpu", "gpu_utilization",
          ]),
          "no NVML data bridged to OTel")
    check("hw.type=gpu or hardware attributes present",
          any(attr in app_content for attr in [
              "hw.type", "hw.id", "hw.vendor", "hw.name", "NVIDIA",
          ]),
          "no OTel hardware semantic convention attributes found")

    otel_slos   = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")
    print("\n.otel/ output file checks:")
    check(".otel/slos.json created", os.path.exists(otel_slos))
    check(".otel/golden-paths.md created", os.path.exists(otel_golden))

finally:
    failed_checks = [n for s, n, _ in CHECKS if s == "FAIL"]
    if failed_checks:
        print(f"\n  NOTE: Workspace preserved for inspection: {tmpdir}")
    else:
        shutil.rmtree(tmpdir, ignore_errors=True)

# ── Final summary ──────────────────────────────────────────────────────────────
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
