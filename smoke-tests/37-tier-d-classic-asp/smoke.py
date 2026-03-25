#!/usr/bin/env python3
"""
E2E "Observe this project." — Tier D Classic ASP / VBScript (default.asp)
==========================================================================
Runs `claude -p "Observe this project."` on a blank Classic ASP insurance
quote form.  Because Classic ASP on IIS 6.0 has no OTel SDK, the agent
must assign Tier D (sidecar bridge) and:

  1. Copy otel-sidecar.py into the project directory
  2. Add HTTP POST calls (MSXML2.ServerXMLHTTP / WinHttp) to default.asp
     so that quote_form, underwriting_rules, and DB steps emit spans
  3. Create .otel/slos.json and .otel/golden-paths.md

Run:
    cd smoke-tests && python3 37-tier-d-classic-asp/smoke.py
"""

import os
import sys
import time
import json
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

SVC         = "37-tier-d-classic-asp"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-classic-asp")
SIDECAR_SRC = os.path.join(os.path.dirname(__file__), "../../otel-sidecar/otel-sidecar.py")

CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

SIDECAR_PORT = 19437

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))


print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-classic-asp (no OTel, no sidecar)")
print(f"  Agent:   claude -p (non-interactive)")
print()

# ── Step 1: Prerequisites ──────────────────────────────────────────────────────
print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
check("claude CLI is installed", claude_bin is not None)
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD))
check("Fixture directory exists", os.path.isdir(FIXTURE_DIR))
check("otel-sidecar.py source exists", os.path.exists(SIDECAR_SRC))

asp_path = os.path.join(FIXTURE_DIR, "default.asp")
if os.path.exists(asp_path):
    asp_content = open(asp_path).read()
    check("Fixture ASP has no sidecar calls yet",
          "otel-sidecar" not in asp_content.lower()
          and "sidecar" not in asp_content.lower(),
          "fixture already has sidecar references")

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
print("Step 2: Setting up blank Classic ASP workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-asp-")
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
    subprocess.run(["git", "commit", "-m", "initial: blank Classic ASP, no observability"],
                   cwd=tmpdir, capture_output=True, check=True)

    check("Temp workspace created", True, tmpdir)
    print(f"  Workspace: {tmpdir}\n")

    # ── Step 3: Run "Observe this project." ───────────────────────────────────
    print("Step 3: Running claude -p 'Observe this project.' ...")
    observe_prompt = f"Observe this project.\nMy Elastic endpoint: {ENDPOINT}\nMy Elastic API key: {API_KEY}"

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

    # ── Step 4: Inspect changes ────────────────────────────────────────────────
    print("\nStep 4: Inspecting what the agent changed")
    diff = subprocess.run(["git", "diff", "HEAD"], cwd=tmpdir, capture_output=True, text=True).stdout
    new_files = [f.strip() for f in subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=tmpdir, capture_output=True, text=True).stdout.splitlines() if f.strip()]

    print(f"  Diff lines: {len(diff.splitlines())}  New files: {new_files}")

    all_text = "\n".join(
        open(os.path.join(tmpdir, f)).read()
        for f in os.listdir(tmpdir)
        if os.path.isfile(os.path.join(tmpdir, f)) and not f.startswith(".") and f != "CLAUDE.md"
    )

    sidecar_path = os.path.join(tmpdir, "otel-sidecar.py")
    otel_slos    = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden  = os.path.join(tmpdir, ".otel", "golden-paths.md")

    print("\nTier D (sidecar bridge) checks:")
    check("otel-sidecar.py added to project",
          os.path.exists(sidecar_path) or any("otel-sidecar" in f for f in new_files))

    has_http = any(kw in all_text.lower() for kw in [
        "http post", "winhttp", "xmlhttp", "serverxmlhttp", "otel-sidecar",
        "start_span", "sidecar", "curl",
    ])
    check("ASP or helper contains HTTP sidecar calls", has_http)

    has_span_names = any(name in all_text for name in [
        "quote_form", "underwriting_rules", "ADODB", "quote_form.asp",
        "ASP.quote_form", "InsuranceDB",
    ])
    check("Correct ASP span names referenced", has_span_names)

    has_biz_attrs = any(attr in all_text for attr in [
        "asp.session_id", "insurance.coverage", "insurance.quote_id",
        "asp.page", "insurance.annual_premium",
    ])
    check("Business span attributes referenced (asp.*/insurance.*)", has_biz_attrs)

    print("\n.otel/ output file checks:")
    check(".otel/slos.json created", os.path.exists(otel_slos))
    if os.path.exists(otel_slos):
        try:
            slos_raw = json.load(open(otel_slos))
            check(".otel/slos.json is valid JSON",
                  isinstance(slos_raw, (list, dict)))
        except json.JSONDecodeError as e:
            check(".otel/slos.json is valid JSON", False, str(e))
    check(".otel/golden-paths.md created", os.path.exists(otel_golden))

    # ── Step 5: Start sidecar and send simulated payloads ─────────────────────
    print("\nStep 5: Starting otel-sidecar.py and sending simulated ASP payloads")

    sidecar_py = sidecar_path if os.path.exists(sidecar_path) else SIDECAR_SRC
    sidecar_env = os.environ.copy()
    sidecar_env.update({
        "OTEL_SERVICE_NAME": SVC, "ELASTIC_OTLP_ENDPOINT": ENDPOINT,
        "ELASTIC_API_KEY": API_KEY, "OTEL_DEPLOYMENT_ENVIRONMENT": "smoke-test",
        "SIDECAR_PORT": str(SIDECAR_PORT),
    })

    sidecar_proc = subprocess.Popen(
        [sys.executable, sidecar_py], env=sidecar_env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    import urllib.request

    sidecar_up = False
    for _ in range(30):
        try:
            resp = urllib.request.urlopen(urllib.request.Request(
                f"http://127.0.0.1:{SIDECAR_PORT}/",
                data=b'{"action":"health"}',
                headers={"Content-Type": "application/json"}, method="POST"), timeout=1)
            if resp.status == 200:
                sidecar_up = True
                break
        except Exception:
            time.sleep(0.3)

    check("otel-sidecar started and responds to health check", sidecar_up)

    if sidecar_up:
        print(f"  Sidecar running on port {SIDECAR_PORT}")
        print("\nStep 6: Sending simulated ASP quote span payloads")

        def post(payload):
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{SIDECAR_PORT}/",
                data=data, headers={"Content-Type": "application/json"}, method="POST")
            return json.loads(urllib.request.urlopen(req, timeout=5).read())

        QUOTE_REQUESTS = [
            {"session": "SESS-A1B2", "applicant": "James Wilson",  "coverage": "auto",      "age": 34},
            {"session": "SESS-C3D4", "applicant": "Maria Gomez",   "coverage": "homeowner", "age": 52},
            {"session": "SESS-E5F6", "applicant": "Robert Kim",    "coverage": "auto",      "age": 28},
        ]

        try:
            for req_data in QUOTE_REQUESTS:
                r = post({
                    "action": "start_span",
                    "name": "ASP.quote_form.asp",
                    "kind": "server",
                    "attributes": {
                        "http.method": "POST",
                        "asp.page": "quote_form.asp",
                        "asp.session_id": req_data["session"],
                        "insurance.coverage_type": req_data["coverage"],
                    },
                })
                page_id = r["span_id"]
                tp = r["traceparent"]
                check(f"start_span ASP.quote_form.asp ({req_data['coverage']}) → ok",
                      r.get("ok") is True, str(r))

                r2 = post({
                    "action": "start_span",
                    "name": "ASP.ADODB.Connection.Execute",
                    "kind": "client",
                    "traceparent": tp,
                    "attributes": {"db.system": "mssql", "db.operation": "SELECT",
                                   "db.name": "InsuranceDB"},
                })
                post({"action": "end_span", "span_id": r2["span_id"],
                      "attributes": {"db.rows_returned": 5}})

                r3 = post({
                    "action": "start_span",
                    "name": "ASP.underwriting_rules",
                    "kind": "internal",
                    "traceparent": tp,
                    "attributes": {"insurance.coverage": req_data["coverage"],
                                   "applicant.age": req_data["age"]},
                })
                premium = 1400.0 if req_data["coverage"] == "auto" else 2100.0
                post({"action": "end_span", "span_id": r3["span_id"],
                      "attributes": {"insurance.annual_premium": premium}})

                post({"action": "end_span", "span_id": page_id,
                      "attributes": {"insurance.annual_premium": premium,
                                     "http.status_code": 200}})

            check(f"Quote spans sent for {len(QUOTE_REQUESTS)} requests", True)

            post({"action": "metric_counter", "name": "asp.quotes_generated",
                  "value": len(QUOTE_REQUESTS), "attributes": {}})

        except Exception as exc:
            check("Sidecar payload simulation completed without error", False, str(exc))

        print("\n  Waiting 3s for OTLP export to Elastic...")
        time.sleep(3)
        check("Sidecar process still alive after payload simulation",
              sidecar_proc.poll() is None)

    if sidecar_proc.poll() is None:
        sidecar_proc.terminate()
        sidecar_proc.wait(timeout=5)

finally:
    failed_checks = [n for s, n, _ in CHECKS if s == "FAIL"]
    if failed_checks:
        print(f"\n  NOTE: Workspace preserved for inspection: {tmpdir}")
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
print(f"  Kibana -> APM -> {SVC}")
if failed:
    sys.exit(1)
