#!/usr/bin/env python3
"""
Eval test: Data Ingestion Pipeline (ingest-api core service)
=============================================================
Runs `claude -p "Observe this project."` on the blank ingest-api Flask service
(fixtures/blank-ingest-api/) and verifies the agent adds correct OTel instrumentation.

Services modeled: ingest-api + schema-validator + dedup + transform + enrichment + storage + indexer

Run:
    cd smoke-tests && python3 62-data-pipeline/smoke.py
"""

import os
import sys
import shutil
import subprocess
import tempfile
import time
import json
import urllib.request
import urllib.error

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")

if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set")
    sys.exit(0)

SVC         = "62-data-pipeline"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-ingest-api")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []

def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-ingest-api (Data pipeline, Flask, no OTel)")
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
    for f in ["app.py", "requirements.txt"]
    if os.path.exists(os.path.join(FIXTURE_DIR, f))
), "fixture already contains opentelemetry — test is invalid")

if any(s == "FAIL" for s, _, _ in CHECKS):
    for status, name, detail in CHECKS:
        print(f"  [{status}] {name}" + (f"\n         -> {detail}" if detail and status == "FAIL" else ""))
    sys.exit(1)

print("  [PASS] all prerequisites met\n")

# ── Step 2: Workspace ──────────────────────────────────────────────────────────
print("Step 2: Setting up blank app workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-pipeline-")
try:
    for fname in os.listdir(FIXTURE_DIR):
        src = os.path.join(FIXTURE_DIR, fname)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(tmpdir, fname))
    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))
    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@edot-autopilot"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot Eval"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial: blank ingest API, no observability"],
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

    # ── Step 4: Verify ─────────────────────────────────────────────────────────
    req_file = os.path.join(tmpdir, "requirements.txt")
    app_file = os.path.join(tmpdir, "app.py")
    req_content = open(req_file).read() if os.path.exists(req_file) else ""
    app_content = open(app_file).read() if os.path.exists(app_file) else ""
    otel_slos   = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")

    print("\nCode correctness checks:")
    check("opentelemetry-sdk in requirements.txt",
          "opentelemetry-sdk" in req_content or "opentelemetry-api" in req_content, req_content)
    check("Flask instrumentation added", "opentelemetry-instrumentation-flask" in req_content, req_content)
    check("OTLP exporter added", "opentelemetry-exporter-otlp" in req_content, req_content)
    check("FlaskInstrumentor applied",
          "FlaskInstrumentor" in app_content and ".instrument(" in app_content,
          "FlaskInstrumentor not found")
    check("Elastic endpoint configured",
          "ELASTIC_OTLP_ENDPOINT" in app_content or "OTLP_ENDPOINT" in app_content
          or ENDPOINT.split("//")[-1][:20] in app_content, "endpoint not in app.py")
    print("\n.otel/ output file checks:")
    check(".otel/slos.json created", os.path.exists(otel_slos))
    check(".otel/golden-paths.md created", os.path.exists(otel_golden))

    # ── Step 5: Run instrumented app ───────────────────────────────────────────
    print("\nStep 5: Running instrumented app")
    pip_result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-r", req_file, "--no-warn-script-location"],
        capture_output=True, text=True
    )
    check("pip install succeeded", pip_result.returncode == 0,
          pip_result.stderr[-300:] if pip_result.returncode != 0 else "")

    if pip_result.returncode == 0:
        PORT = 16062
        env = os.environ.copy()
        env["PORT"] = str(PORT)
        app_proc = subprocess.Popen(
            [sys.executable, app_file], cwd=tmpdir, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        started = False
        for _ in range(30):
            try:
                r = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=0.5)
                if r.status == 200:
                    started = True
                    break
            except Exception:
                time.sleep(0.3)
        check("Instrumented app starts and responds to /health", started)

        if started:
            try:
                data = json.dumps({
                    "source": "eval-test",
                    "events": [{"event_type": "page_view", "user_id": "u1", "ts": "2024-01-01T00:00:00Z"}],
                }).encode()
                r2 = urllib.request.urlopen(
                    urllib.request.Request(
                        f"http://127.0.0.1:{PORT}/ingest",
                        data=data, headers={"Content-Type": "application/json"}, method="POST",
                    ), timeout=10
                )
                check("POST /ingest returns 201 or pipeline error",
                      r2.status in (201, 422, 500, 503), f"status={r2.status}")
            except urllib.error.HTTPError as e:
                check("POST /ingest returns 201 or pipeline error",
                      e.code in (201, 422, 500, 503), f"HTTP {e.code}")
            except Exception as e:
                check("POST /ingest returns 201 or pipeline error", False, str(e))

        if app_proc.poll() is None:
            app_proc.terminate()
            app_proc.wait(timeout=5)

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
print(f"  Kibana → APM → ingest-api (data-pipeline)")
if failed:
    sys.exit(1)
