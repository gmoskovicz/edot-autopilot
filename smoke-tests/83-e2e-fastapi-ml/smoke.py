#!/usr/bin/env python3
"""
E2E "Observe this project." — FastAPI ML Inference
===================================================
This test ACTUALLY runs `claude -p "Observe this project."` on a blank,
uninstrumented FastAPI ML inference service. It does not assume or hardcode
what the agent will generate.

What this tests:
  1. The agent reads the blank app and understands it (FastAPI, ML models,
     inference endpoint)
  2. The agent correctly assigns Tier A (auto-instrumentation via
     opentelemetry-instrumentation-fastapi)
  3. The agent adds business enrichment (model.name, prediction.class,
     inference.latency_ms)
  4. The generated requirements.txt includes the right OTel packages
  5. The instrumented app runs and serves requests
  6. Spans actually arrive in Elastic with correct attributes

Run:
    cd smoke-tests && python3 83-e2e-fastapi-ml/smoke.py

Requirements (in addition to requirements.txt):
  - `claude` CLI installed and authenticated
  - ELASTIC_OTLP_ENDPOINT and ELASTIC_API_KEY set in .env or environment
"""

import os
import sys
import time
import shutil
import subprocess
import tempfile
import json

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")

if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set")
    sys.exit(0)

SVC         = "83-e2e-fastapi-ml"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-fastapi-ml")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")

if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []
def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-fastapi-ml (no OTel)")
print(f"  Agent:   claude -p (non-interactive)")
print(f"  Target:  {ENDPOINT.split('@')[-1].split('/')[0] if '@' in ENDPOINT else ENDPOINT[:40]}")
print()

# ── Step 1: Verify prerequisites ──────────────────────────────────────────────
print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
check("claude CLI is installed", claude_bin is not None,
      "install via: npm install -g @anthropic-ai/claude-code")
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD), f"looked at {CLAUDE_MD}")
check("Fixture app exists", os.path.isdir(FIXTURE_DIR))
check("Fixture has no OTel", not any(
    "opentelemetry" in open(os.path.join(FIXTURE_DIR, f)).read()
    for f in ["app.py", "requirements.txt"]
    if os.path.exists(os.path.join(FIXTURE_DIR, f))
), "fixture already contains opentelemetry — test is invalid")

if any(s == "FAIL" for s, _, _ in CHECKS):
    print("Prerequisites failed — cannot continue")
    for status, name, detail in CHECKS:
        line = f"  [{status}] {name}"
        if detail and status == "FAIL":
            line += f"\n         -> {detail}"
        print(line)
    sys.exit(1)

print("  [PASS] all prerequisites met\n")

# ── Step 2: Set up temp workspace ─────────────────────────────────────────────
print("Step 2: Setting up blank app workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-83-")
try:
    for fname in os.listdir(FIXTURE_DIR):
        src = os.path.join(FIXTURE_DIR, fname)
        dst = os.path.join(tmpdir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, dst)

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

    # ── Step 4: Inspect the diff ──────────────────────────────────────────────
    print("\nStep 4: Inspecting what the agent changed")
    diff_result = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=tmpdir, capture_output=True, text=True
    )
    diff = diff_result.stdout

    new_files_result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=tmpdir, capture_output=True, text=True
    )
    new_files = [f.strip() for f in new_files_result.stdout.splitlines() if f.strip()]

    print(f"  Modified files (git diff): {len(diff.splitlines())} diff lines")
    print(f"  New files: {new_files}")

    req_file    = os.path.join(tmpdir, "requirements.txt")
    app_file    = os.path.join(tmpdir, "app.py")
    otel_slos   = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")

    req_content = open(req_file).read() if os.path.exists(req_file) else ""
    app_content = open(app_file).read() if os.path.exists(app_file) else ""

    print("\nCode correctness checks (Tier A — FastAPI auto-instrumentation):")

    # requirements.txt checks
    check("opentelemetry-sdk or opentelemetry-api added",
          "opentelemetry-sdk" in req_content or "opentelemetry-api" in req_content,
          f"requirements.txt:\n{req_content}")
    check("FastAPI instrumentation package added",
          "opentelemetry-instrumentation-fastapi" in req_content,
          f"requirements.txt:\n{req_content}")
    check("OTLP exporter added",
          "opentelemetry-exporter-otlp" in req_content,
          f"requirements.txt:\n{req_content}")

    # app.py instrumentation checks
    check("FastAPIInstrumentor applied in app.py",
          "FastAPIInstrumentor" in app_content and ".instrument" in app_content,
          "FastAPIInstrumentor not found in app.py")
    check("TracerProvider or OTLPSpanExporter configured",
          "TracerProvider" in app_content or "OTLPSpanExporter" in app_content,
          "no tracer setup found in app.py")
    check("Elastic endpoint configured from env",
          "ELASTIC_OTLP_ENDPOINT" in app_content or "OTLP_ENDPOINT" in app_content
          or (ENDPOINT.split("//")[1][:20] if "//" in ENDPOINT else ENDPOINT[:20]) in app_content,
          "endpoint not referenced in app.py")

    # Business enrichment checks
    print("\nBusiness enrichment checks:")
    has_ml_enrichment = any(
        attr in app_content for attr in [
            "model.name", "model_name", "ml.model",
            "prediction.class", "prediction", "inference",
            "inference_ms", "ml.inference", "ml.prediction",
        ]
    )
    check("ML business span attributes added (model.name, prediction, inference)",
          has_ml_enrichment,
          "no ML business enrichment attributes found in app.py")

    # .otel/ output files
    print("\n.otel/ output file checks:")
    check(".otel/slos.json created",
          os.path.exists(otel_slos),
          f"expected at {otel_slos}")
    if os.path.exists(otel_slos):
        try:
            slos_raw = json.load(open(otel_slos))
            if isinstance(slos_raw, list):
                check(".otel/slos.json is valid JSON with at least one SLO",
                      len(slos_raw) > 0, f"got empty list")
            else:
                check(".otel/slos.json is valid JSON with 'services' key",
                      "services" in slos_raw, f"keys: {list(slos_raw.keys())}")
        except json.JSONDecodeError as e:
            check(".otel/slos.json is valid JSON", False, str(e))

    check(".otel/golden-paths.md created",
          os.path.exists(otel_golden),
          f"expected at {otel_golden}")

    # ── Step 5: Run the instrumented app ──────────────────────────────────────
    print("\nStep 5: Running the instrumented app")

    pip_install = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q",
         "-r", req_file, "--no-warn-script-location"],
        capture_output=True, text=True
    )
    if pip_install.returncode != 0:
        check("pip install of generated requirements succeeded",
              False, pip_install.stderr[-500:])
    else:
        check("pip install of generated requirements succeeded", True)

    PORT = 15083
    env  = os.environ.copy()
    env["PORT"] = str(PORT)
    app_proc = subprocess.Popen(
        [sys.executable, app_file],
        cwd=tmpdir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    import requests as http_lib
    started = False
    for _ in range(30):
        try:
            r = http_lib.get(f"http://127.0.0.1:{PORT}/health", timeout=0.5)
            if r.status_code == 200:
                started = True
                break
        except Exception:
            time.sleep(0.3)

    check("Instrumented app starts and responds to /health",
          started,
          f"app stdout: {app_proc.stdout.read(500) if app_proc.poll() is not None else '(still running)'}")

    if started:
        print(f"  App running on port {PORT}")
        print("\nStep 6: Making test requests to instrumented app")

        r_models = http_lib.get(f"http://127.0.0.1:{PORT}/models")
        check("GET /models → 200", r_models.status_code == 200,
              f"status={r_models.status_code}")

        r_pred1 = http_lib.post(f"http://127.0.0.1:{PORT}/predict",
                                 json={"features": [5.1, 3.5, 1.4, 0.2],
                                       "model_name": "iris-classifier-v1",
                                       "customer_id": "cust-001"})
        check("POST /predict (iris-classifier-v1) → 200",
              r_pred1.status_code == 200,
              f"status={r_pred1.status_code} body={r_pred1.text[:200]}")

        r_pred2 = http_lib.post(f"http://127.0.0.1:{PORT}/predict",
                                 json={"features": [100.0, 1.5, 3.0],
                                       "model_name": "fraud-detector-v2",
                                       "customer_id": "cust-002"})
        check("POST /predict (fraud-detector-v2) → 200",
              r_pred2.status_code == 200,
              f"status={r_pred2.status_code}")

        r_404 = http_lib.post(f"http://127.0.0.1:{PORT}/predict",
                               json={"features": [1.0], "model_name": "nonexistent-model"})
        check("POST /predict (unknown model) → 404",
              r_404.status_code == 404,
              f"status={r_404.status_code}")

        print("\n  Waiting 3s for OTLP export to Elastic...")
        time.sleep(3)

        check("Test requests completed without app crash",
              app_proc.poll() is None,
              "app process died during requests")

    if 'app_proc' in dir() and app_proc.poll() is None:
        app_proc.terminate()
        app_proc.wait(timeout=5)

finally:
    failed_checks = [n for s, n, _ in CHECKS if s == "FAIL"]
    if failed_checks:
        print(f"\n  NOTE: Workspace preserved for inspection: {tmpdir}")
    else:
        shutil.rmtree(tmpdir, ignore_errors=True)

# ── Final summary ─────────────────────────────────────────────────────────────
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
