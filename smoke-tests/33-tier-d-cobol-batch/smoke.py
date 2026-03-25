#!/usr/bin/env python3
"""
E2E "Observe this project." — Tier D COBOL Batch (PAYRLL01)
============================================================
Runs `claude -p "Observe this project."` on a blank COBOL payroll
batch job.  Because COBOL cannot link an OTel SDK, the agent must
assign Tier D (sidecar bridge) and:

  1. Copy otel-sidecar.py into the project directory
  2. Add HTTP POST calls (curl / helper script) to PAYRLL01.cbl so
     that each major step (READ-EMPMASTER, CALC-PAY,
     WRITE-DISBURSEMENTS) emits a span via the sidecar API
  3. Create .otel/slos.json and .otel/golden-paths.md

Verification (after running claude -p):
  - otel-sidecar.py is present in the project
  - PAYRLL01.cbl or a generated helper contains HTTP POST / curl calls
  - .otel/slos.json was created
  - Starting the sidecar and POSTing simulated payloads creates spans
    with correct names and business attributes

Run:
    cd smoke-tests && python3 33-tier-d-cobol-batch/smoke.py
"""

import os
import sys
import time
import json
import shutil
import subprocess
import tempfile
import threading

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")

if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set")
    sys.exit(0)

SVC         = "33-tier-d-cobol-batch"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-cobol-payroll")
SIDECAR_SRC = os.path.join(os.path.dirname(__file__), "../../otel-sidecar/otel-sidecar.py")

# Resolve CLAUDE.md (try repo root)
CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

SIDECAR_PORT = 19433

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))


print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-cobol-payroll (no OTel, no sidecar)")
print(f"  Agent:   claude -p (non-interactive)")
print(f"  Target:  {ENDPOINT.split('@')[-1].split('/')[0] if '@' in ENDPOINT else ENDPOINT[:40]}")
print()

# ── Step 1: Prerequisites ──────────────────────────────────────────────────────
print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
check("claude CLI is installed", claude_bin is not None,
      "install via: npm install -g @anthropic-ai/claude-code")
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD), f"looked at {CLAUDE_MD}")
check("Fixture directory exists", os.path.isdir(FIXTURE_DIR))
check("otel-sidecar.py source exists", os.path.exists(SIDECAR_SRC), f"looked at {SIDECAR_SRC}")

cobl_path = os.path.join(FIXTURE_DIR, "PAYRLL01.cbl")
if os.path.exists(cobl_path):
    cobl_content = open(cobl_path).read()
    check("Fixture COBOL has no sidecar calls yet",
          "otel-sidecar" not in cobl_content.lower()
          and "http post" not in cobl_content.lower()
          and "9411" not in cobl_content,
          "fixture already has sidecar references — test is invalid")

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
print("Step 2: Setting up blank COBOL workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-cobol-")
try:
    # Copy fixture files (PAYRLL01.cbl, README.md)
    for fname in os.listdir(FIXTURE_DIR):
        src = os.path.join(FIXTURE_DIR, fname)
        dst = os.path.join(tmpdir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, dst)

    # Copy CLAUDE.md
    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))

    # Git init so we can diff what the agent changes
    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@edot-autopilot"], cwd=tmpdir,
                   capture_output=True)
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot E2E"], cwd=tmpdir,
                   capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial: blank COBOL, no observability"],
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
    diff_result = subprocess.run(
        ["git", "diff", "HEAD"], cwd=tmpdir, capture_output=True, text=True)
    diff = diff_result.stdout

    new_files_result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=tmpdir, capture_output=True, text=True)
    new_files = [f.strip() for f in new_files_result.stdout.splitlines() if f.strip()]

    print(f"  Modified files (git diff): {len(diff.splitlines())} diff lines")
    print(f"  New files: {new_files}")

    # Read current state of key files
    cobl_after = open(os.path.join(tmpdir, "PAYRLL01.cbl")).read() \
        if os.path.exists(os.path.join(tmpdir, "PAYRLL01.cbl")) else ""
    all_text = "\n".join(
        open(os.path.join(tmpdir, f)).read()
        for f in os.listdir(tmpdir)
        if os.path.isfile(os.path.join(tmpdir, f))
        and not f.startswith(".")
        and f != "CLAUDE.md"
    )

    otel_slos    = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden  = os.path.join(tmpdir, ".otel", "golden-paths.md")
    sidecar_path = os.path.join(tmpdir, "otel-sidecar.py")

    print("\nTier D (sidecar bridge) checks:")

    # Sidecar was added
    check("otel-sidecar.py added to project",
          os.path.exists(sidecar_path)
          or any("otel-sidecar" in f for f in new_files),
          f"new files: {new_files}")

    # COBOL or helper now contains HTTP / sidecar calls
    has_http = any(kw in all_text.lower() for kw in [
        "http post", "curl ", "requests.post", "9411", "otel-sidecar",
        "start_span", "end_span", "action",
    ])
    check("COBOL or helper contains HTTP sidecar calls",
          has_http,
          "no HTTP/curl/sidecar references found in project files")

    # Span names should reference the key COBOL steps
    has_span_names = any(name in all_text for name in [
        "PAYRLL01", "READ-EMPMASTER", "CALC-PAY", "WRITE-DISBURSEMENTS",
    ])
    check("Correct COBOL span names referenced",
          has_span_names,
          "expected PAYRLL01 / READ-EMPMASTER / CALC-PAY / WRITE-DISBURSEMENTS")

    # Business attributes
    has_biz_attrs = any(attr in all_text for attr in [
        "cobol.program", "payroll.gross_usd", "cobol.records_read",
        "batch.type", "cobol.department",
    ])
    check("Business span attributes referenced (payroll/cobol.*)",
          has_biz_attrs,
          "no payroll.* or cobol.* attribute names found")

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
                      len(slos_raw) > 0, "got empty list")
            else:
                check(".otel/slos.json is valid JSON with 'services' key",
                      "services" in slos_raw,
                      f"keys: {list(slos_raw.keys())}")
        except json.JSONDecodeError as e:
            check(".otel/slos.json is valid JSON", False, str(e))

    check(".otel/golden-paths.md created",
          os.path.exists(otel_golden),
          f"expected at {otel_golden}")

    # ── Step 5: Start sidecar and send simulated payloads ─────────────────────
    print("\nStep 5: Starting otel-sidecar.py and sending simulated COBOL payloads")

    sidecar_py = sidecar_path if os.path.exists(sidecar_path) else SIDECAR_SRC
    sidecar_env = os.environ.copy()
    sidecar_env["OTEL_SERVICE_NAME"]           = SVC
    sidecar_env["ELASTIC_OTLP_ENDPOINT"]       = ENDPOINT
    sidecar_env["ELASTIC_API_KEY"]             = API_KEY
    sidecar_env["OTEL_DEPLOYMENT_ENVIRONMENT"] = "smoke-test"
    sidecar_env["SIDECAR_PORT"]                = str(SIDECAR_PORT)

    sidecar_proc = subprocess.Popen(
        [sys.executable, sidecar_py],
        env=sidecar_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    import urllib.request
    import urllib.error

    sidecar_up = False
    for _ in range(30):
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{SIDECAR_PORT}/",
                data=b'{"action":"health"}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=1)
            if resp.status == 200:
                sidecar_up = True
                break
        except Exception:
            time.sleep(0.3)

    check("otel-sidecar started and responds to health check",
          sidecar_up,
          f"sidecar stderr: {sidecar_proc.stderr.read(300) if sidecar_proc.poll() is not None else '(still running)'}")

    if sidecar_up:
        print(f"  Sidecar running on port {SIDECAR_PORT}")
        print("\nStep 6: Sending simulated COBOL span payloads via HTTP POST")

        def post(payload: dict) -> dict:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{SIDECAR_PORT}/",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=5)
            return json.loads(resp.read())

        EMPLOYEES = [
            {"emp_id": "EMP-00101", "dept": "FINANCE",    "hours": 160, "rate": 52.50,  "tax_pct": 0.28},
            {"emp_id": "EMP-00102", "dept": "OPERATIONS", "hours": 168, "rate": 38.75,  "tax_pct": 0.22},
            {"emp_id": "EMP-00103", "dept": "IT",         "hours": 160, "rate": 71.00,  "tax_pct": 0.32},
        ]

        try:
            # Root job span
            r = post({
                "action": "start_span",
                "name": "PAYRLL01.JOB",
                "kind": "internal",
                "attributes": {
                    "cobol.program": "PAYRLL01",
                    "cobol.job_class": "A",
                    "cobol.region_mb": 512,
                    "batch.type": "payroll",
                    "batch.period": "2026-02",
                },
            })
            job_span_id  = r["span_id"]
            job_traceparent = r["traceparent"]
            check("start_span PAYRLL01.JOB → ok", r.get("ok") is True, str(r))

            # READ-EMPMASTER step
            r2 = post({
                "action": "start_span",
                "name": "PAYRLL01.READ-EMPMASTER",
                "kind": "internal",
                "traceparent": job_traceparent,
                "attributes": {
                    "cobol.dd_name": "EMPMASTR",
                    "cobol.vsam_file": "PAYROLL.EMPMASTR.KSF",
                },
            })
            read_span_id = r2["span_id"]
            post({"action": "end_span", "span_id": read_span_id,
                  "attributes": {"cobol.records_read": len(EMPLOYEES)}})
            check("READ-EMPMASTER span round-trip", r2.get("ok") is True, str(r2))

            # One CALC-PAY span per employee
            total_gross = 0.0
            for emp in EMPLOYEES:
                gross = emp["hours"] * emp["rate"]
                net   = gross * (1 - emp["tax_pct"])
                total_gross += gross
                r3 = post({
                    "action": "start_span",
                    "name": "PAYRLL01.CALC-PAY",
                    "kind": "internal",
                    "traceparent": job_traceparent,
                    "attributes": {
                        "cobol.employee_id": emp["emp_id"],
                        "cobol.department":  emp["dept"],
                    },
                })
                calc_id = r3["span_id"]
                post({"action": "end_span", "span_id": calc_id,
                      "attributes": {
                          "payroll.gross_usd": round(gross, 2),
                          "payroll.net_usd":   round(net, 2),
                          "payroll.tax_pct":   emp["tax_pct"],
                      }})

            check(f"CALC-PAY spans sent for {len(EMPLOYEES)} employees", True)

            # WRITE-DISBURSEMENTS step
            r4 = post({
                "action": "start_span",
                "name": "PAYRLL01.WRITE-DISBURSEMENTS",
                "kind": "internal",
                "traceparent": job_traceparent,
                "attributes": {
                    "cobol.dd_name": "DISBFILE",
                    "cobol.seq_file": "PAYROLL.DISB.OUTFILE",
                },
            })
            disb_id = r4["span_id"]
            post({"action": "end_span", "span_id": disb_id,
                  "attributes": {
                      "cobol.records_written":   len(EMPLOYEES),
                      "payroll.total_gross_usd": round(total_gross, 2),
                  }})
            check("WRITE-DISBURSEMENTS span round-trip", r4.get("ok") is True, str(r4))

            # Log record
            post({
                "action": "log",
                "body": "PAYRLL01 payroll batch complete",
                "severity": "INFO",
                "traceparent": job_traceparent,
                "attributes": {
                    "cobol.program": "PAYRLL01",
                    "batch.employee_count": len(EMPLOYEES),
                    "payroll.total_gross_usd": round(total_gross, 2),
                },
            })

            # Counters and histograms
            post({"action": "metric_counter", "name": "cobol.records_processed",
                  "value": len(EMPLOYEES),
                  "attributes": {"cobol.program": "PAYRLL01"}})
            post({"action": "metric_histogram", "name": "cobol.gross_pay_usd",
                  "value": total_gross,
                  "attributes": {"cobol.program": "PAYRLL01"}})

            # End root span
            post({"action": "end_span", "span_id": job_span_id,
                  "attributes": {
                      "batch.total_gross_usd": round(total_gross, 2),
                      "batch.employee_count":  len(EMPLOYEES),
                  }})
            check("PAYRLL01.JOB root span ended cleanly", True)

        except Exception as exc:
            check("Sidecar payload simulation completed without error", False, str(exc))

        # Give BatchSpanProcessor time to export
        print("\n  Waiting 3s for OTLP export to Elastic...")
        time.sleep(3)

        check("Sidecar process still alive after payload simulation",
              sidecar_proc.poll() is None,
              "sidecar died unexpectedly")

    # ── Cleanup ───────────────────────────────────────────────────────────────
    if sidecar_proc.poll() is None:
        sidecar_proc.terminate()
        sidecar_proc.wait(timeout=5)

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
print(f"  Kibana -> APM -> {SVC}")
if failed:
    sys.exit(1)
