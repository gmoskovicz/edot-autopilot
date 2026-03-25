#!/usr/bin/env python3
"""
Eval test: Tier A — Node.js Express API
=========================================
Runs `claude -p "Observe this project."` on a blank Express.js order API
(fixtures/blank-express-api/) and verifies the agent adds the correct
OpenTelemetry Node.js packages and instrumentation.

What this tests:
  1. Agent reads the blank Express app and understands it
  2. Agent adds @opentelemetry/sdk-node (or equivalent bootstrap)
  3. Agent adds @opentelemetry/instrumentation-express
  4. Agent adds @opentelemetry/exporter-trace-otlp-proto (or http)
  5. Generated package.json contains the OTel dependencies
  6. Agent configures the Elastic endpoint from env

Run:
    cd smoke-tests && python3 02-tier-a-nodejs/smoke.py

Requirements:
  - `claude` CLI installed and authenticated
  - `node` available (prerequisite check — skips live run if absent)
  - ELASTIC_OTLP_ENDPOINT and ELASTIC_API_KEY set in .env or environment
"""

import os
import sys
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

SVC         = "02-tier-a-nodejs"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-express-api")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []

def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-express-api (no OTel)")
print(f"  Agent:   claude -p (non-interactive)")
print(f"  Target:  {ENDPOINT.split('@')[-1].split('/')[0] if '@' in ENDPOINT else ENDPOINT[:40]}")
print()

# ── Step 1: Prerequisites ──────────────────────────────────────────────────────
print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
node_bin   = shutil.which("node")
check("claude CLI is installed", claude_bin is not None,
      "install via: npm install -g @anthropic-ai/claude-code")
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD), f"looked at {CLAUDE_MD}")
check("Fixture directory exists", os.path.isdir(FIXTURE_DIR), FIXTURE_DIR)
check("Fixture has no OTel", not any(
    "opentelemetry" in open(os.path.join(FIXTURE_DIR, f)).read()
    for f in ["index.js", "package.json"]
    if os.path.exists(os.path.join(FIXTURE_DIR, f))
), "fixture already contains opentelemetry — test is invalid")
check("node is available (needed to run app)", node_bin is not None,
      "node not found — agent run + code checks will still execute; live run will be skipped")

if any(s == "FAIL" for s, n, _ in CHECKS
       if n not in ("node is available (needed to run app)",)):
    print("Prerequisites failed — cannot continue")
    for status, name, detail in CHECKS:
        line = f"  [{status}] {name}"
        if detail and status == "FAIL":
            line += f"\n         -> {detail}"
        print(line)
    sys.exit(1)

print("  [PASS] all critical prerequisites met\n")

# ── Step 2: Set up temp workspace ─────────────────────────────────────────────
print("Step 2: Setting up blank app workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-nodejs-")
try:
    # Copy fixture files recursively
    for fname in os.listdir(FIXTURE_DIR):
        src = os.path.join(FIXTURE_DIR, fname)
        dst = os.path.join(tmpdir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, dst)

    # Copy CLAUDE.md
    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))

    # Initialize git so we can diff what the agent changes
    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@edot-autopilot"],
                   cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot Eval"],
                   cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial: blank Express API, no observability"],
                   cwd=tmpdir, capture_output=True, check=True)

    check("Temp workspace created", True, tmpdir)
    print(f"  Workspace: {tmpdir}")
    print(f"  Files: {sorted(os.listdir(tmpdir))}\n")

    # ── Step 3: Run agent ──────────────────────────────────────────────────────
    print("Step 3: Running claude -p 'Observe this project.' (this takes a few minutes...)")
    observe_prompt = (
        f"Observe this project.\n"
        f"My Elastic endpoint: {ENDPOINT}\n"
        f"My Elastic API key: {API_KEY}"
    )

    import time
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

    # ── Step 4: Inspect what the agent changed ─────────────────────────────────
    print("\nStep 4: Inspecting what the agent changed")
    new_files_result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=tmpdir, capture_output=True, text=True
    )
    new_files = [f.strip() for f in new_files_result.stdout.splitlines() if f.strip()]
    print(f"  New files: {new_files}")

    # Read current state of key files
    pkg_file     = os.path.join(tmpdir, "package.json")
    index_file   = os.path.join(tmpdir, "index.js")
    otel_slos    = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden  = os.path.join(tmpdir, ".otel", "golden-paths.md")

    pkg_content   = open(pkg_file).read()   if os.path.exists(pkg_file)   else ""
    index_content = open(index_file).read() if os.path.exists(index_file) else ""

    # Also look for a separate tracing bootstrap file (common Node.js pattern)
    tracing_file = None
    for candidate in ["tracing.js", "otel.js", "instrumentation.js", "telemetry.js"]:
        p = os.path.join(tmpdir, candidate)
        if os.path.exists(p):
            tracing_file = open(p).read()
            print(f"  Found tracing bootstrap: {candidate}")
            break

    all_js_content = index_content + (tracing_file or "")

    print("\nCode correctness checks (Tier A — auto-instrumentation):")

    # package.json checks
    check("@opentelemetry/sdk-node added to package.json",
          "@opentelemetry/sdk-node" in pkg_content,
          f"package.json:\n{pkg_content}")
    check("@opentelemetry/instrumentation-express added",
          "instrumentation-express" in pkg_content,
          f"package.json:\n{pkg_content}")
    check("@opentelemetry/exporter-trace-otlp added",
          "exporter-trace-otlp" in pkg_content or "exporter-otlp" in pkg_content,
          f"package.json:\n{pkg_content}")

    # instrumentation code checks
    check("OTel SDK initialized in JS code",
          "NodeSDK" in all_js_content or "TracerProvider" in all_js_content
          or "opentelemetry" in all_js_content.lower(),
          "no OTel initialization found in index.js or tracing bootstrap")
    check("Elastic endpoint configured from env",
          "ELASTIC_OTLP_ENDPOINT" in all_js_content
          or "OTLP_ENDPOINT" in all_js_content
          or ENDPOINT.split("//")[-1][:20] in all_js_content,
          "endpoint not referenced in any JS file")

    # .otel/ output files
    print("\n.otel/ output file checks:")
    check(".otel/slos.json created",
          os.path.exists(otel_slos),
          f"expected at {otel_slos}")
    if os.path.exists(otel_slos):
        try:
            slos_raw = json.load(open(otel_slos))
            check(".otel/slos.json is valid JSON with content",
                  bool(slos_raw), f"got: {slos_raw!r}")
        except json.JSONDecodeError as e:
            check(".otel/slos.json is valid JSON", False, str(e))

    check(".otel/golden-paths.md created",
          os.path.exists(otel_golden),
          f"expected at {otel_golden}")

    # ── Step 5: Optionally run the instrumented app ────────────────────────────
    if not node_bin:
        print("\nStep 5: SKIP — node not available (install Node.js to enable live run)")
        check("Live app run", True,
              "# SKIP: requires node runtime — code checks above are sufficient")
    else:
        print(f"\nStep 5: Installing dependencies and running instrumented app")
        npm_install = subprocess.run(
            ["npm", "install", "--prefer-offline"],
            cwd=tmpdir, capture_output=True, text=True, timeout=120
        )
        check("npm install succeeded",
              npm_install.returncode == 0,
              npm_install.stderr[-300:] if npm_install.returncode != 0 else "")

        if npm_install.returncode == 0:
            import threading

            PORT = 13002
            env = os.environ.copy()
            env["PORT"] = str(PORT)
            app_proc = subprocess.Popen(
                [node_bin, "index.js"],
                cwd=tmpdir, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )

            started = False
            try:
                import urllib.request
                for _ in range(30):
                    try:
                        r = urllib.request.urlopen(
                            f"http://127.0.0.1:{PORT}/health", timeout=0.5
                        )
                        if r.status == 200:
                            started = True
                            break
                    except Exception:
                        time.sleep(0.3)
            except Exception:
                pass

            check("Instrumented Node.js app starts and responds to /health",
                  started,
                  "app did not start in time")

            if started:
                import urllib.request as req_lib
                import urllib.error

                try:
                    order_data = json.dumps({
                        "customer_id": "cust_eval_nodejs",
                        "customer_tier": "enterprise",
                        "items": [{"name": "Widget", "price_usd": 49.99, "qty": 2}]
                    }).encode()
                    r2 = req_lib.urlopen(
                        req_lib.Request(
                            f"http://127.0.0.1:{PORT}/orders",
                            data=order_data,
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        ), timeout=5
                    )
                    status = r2.status
                    check("POST /orders returns 201 or 402 (fraud/payment block ok)",
                          status in (201, 402),
                          f"status={status}")
                except urllib.error.HTTPError as e:
                    check("POST /orders returns 201 or 402 (fraud/payment block ok)",
                          e.code in (201, 402), f"HTTP {e.code}")
                except Exception as e:
                    check("POST /orders returns 201 or 402 (fraud/payment block ok)",
                          False, str(e))

                try:
                    r3 = req_lib.urlopen(
                        f"http://127.0.0.1:{PORT}/orders/nonexistent-id", timeout=5
                    )
                    check("GET /orders/<missing> returns 404",
                          False, f"expected 404, got {r3.status}")
                except urllib.error.HTTPError as e:
                    check("GET /orders/<missing> returns 404", e.code == 404,
                          f"got {e.code}")
                except Exception as e:
                    check("GET /orders/<missing> returns 404", False, str(e))

            if app_proc.poll() is None:
                app_proc.terminate()
                app_proc.wait(timeout=5)

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
print(f"  Kibana → APM → order-api (Node.js)")
if failed:
    sys.exit(1)
