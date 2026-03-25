#!/usr/bin/env python3
"""
E2E "Observe this project." — Tier D VBA Excel / Group P&L Consolidation
=========================================================================
Runs `claude -p "Observe this project."` on a blank VBA macro workbook.
Because VBA in Excel has no OTel SDK, the agent must assign Tier D and:

  1. Copy otel-sidecar.py into the project directory
  2. Add WinHttp.WinHttpRequest POST calls to macro.vba so that
     Workbook_Open, Range_Read, FX_Conversion, and Range_Write_Consolidation
     each emit spans via the sidecar API
  3. Create .otel/slos.json and .otel/golden-paths.md

Run:
    cd smoke-tests && python3 38-tier-d-vba-excel/smoke.py
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

SVC         = "38-tier-d-vba-excel"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-vba-excel")
SIDECAR_SRC = os.path.join(os.path.dirname(__file__), "../../otel-sidecar/otel-sidecar.py")

CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

SIDECAR_PORT = 19438

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))


print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-vba-excel (no OTel, no sidecar)")
print()

# ── Step 1: Prerequisites ──────────────────────────────────────────────────────
print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
check("claude CLI is installed", claude_bin is not None)
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD))
check("Fixture directory exists", os.path.isdir(FIXTURE_DIR))
check("otel-sidecar.py source exists", os.path.exists(SIDECAR_SRC))

vba_path = os.path.join(FIXTURE_DIR, "macro.vba")
if os.path.exists(vba_path):
    vba_content = open(vba_path).read()
    check("Fixture VBA has no sidecar calls yet",
          "otel-sidecar" not in vba_content.lower()
          and "winhttp" not in vba_content.lower()
          and "sidecar" not in vba_content.lower())

if any(s == "FAIL" for s, _, _ in CHECKS):
    for status, name, detail in CHECKS:
        line = f"  [{status}] {name}"
        if detail and status == "FAIL":
            line += f"\n         -> {detail}"
        print(line)
    sys.exit(1)

print("  [PASS] all prerequisites met\n")

# ── Step 2: Workspace ─────────────────────────────────────────────────────────
print("Step 2: Setting up blank VBA workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-vba-")
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
    subprocess.run(["git", "commit", "-m", "initial: blank VBA, no observability"],
                   cwd=tmpdir, capture_output=True, check=True)
    check("Temp workspace created", True, tmpdir)
    print(f"  Workspace: {tmpdir}\n")

    # ── Step 3: Run agent ─────────────────────────────────────────────────────
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
        for line in result.stdout.strip().splitlines()[-20:]:
            print(f"    {line}")
    check("Agent exited cleanly", result.returncode == 0,
          f"stderr: {result.stderr[-500:] if result.stderr else ''}")

    # ── Step 4: Inspect changes ───────────────────────────────────────────────
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
        "winhttp", "xmlhttp", "otel-sidecar", "start_span", "sidecar", "curl",
    ])
    check("VBA or helper contains HTTP sidecar calls", has_http)
    has_span_names = any(name in all_text for name in [
        "ConsolidatePL", "FX_Conversion", "Workbook_Open", "Range_Read",
        "VBA.Macro", "GroupConsolidation",
    ])
    check("Correct VBA span names referenced", has_span_names)
    has_biz_attrs = any(attr in all_text for attr in [
        "finance.entity", "finance.currency", "finance.fx_rate", "vba.macro",
        "finance.revenue_usd",
    ])
    check("Business span attributes referenced (finance.*/vba.*)", has_biz_attrs)

    print("\n.otel/ output file checks:")
    check(".otel/slos.json created", os.path.exists(otel_slos))
    if os.path.exists(otel_slos):
        try:
            slos_raw = json.load(open(otel_slos))
            check(".otel/slos.json is valid JSON", isinstance(slos_raw, (list, dict)))
        except json.JSONDecodeError as e:
            check(".otel/slos.json is valid JSON", False, str(e))
    check(".otel/golden-paths.md created", os.path.exists(otel_golden))

    # ── Step 5: Sidecar + payload ─────────────────────────────────────────────
    print("\nStep 5: Starting otel-sidecar.py and sending simulated VBA payloads")
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

        def post(payload):
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{SIDECAR_PORT}/",
                data=data, headers={"Content-Type": "application/json"}, method="POST")
            return json.loads(urllib.request.urlopen(req, timeout=5).read())

        SUBSIDIARIES = [
            {"entity": "EMEA-GmbH", "currency": "EUR", "fx_rate": 1.08, "revenue": 4_200_000},
            {"entity": "APAC-Pte",  "currency": "SGD", "fx_rate": 0.74, "revenue": 6_800_000},
            {"entity": "NA-Corp",   "currency": "USD", "fx_rate": 1.00, "revenue": 12_500_000},
        ]

        try:
            for sub in SUBSIDIARIES:
                r = post({
                    "action": "start_span",
                    "name": "VBA.Macro_ConsolidatePL",
                    "kind": "internal",
                    "attributes": {
                        "vba.macro": "ConsolidatePL",
                        "finance.entity": sub["entity"],
                        "finance.currency": sub["currency"],
                        "finance.fx_rate": sub["fx_rate"],
                    },
                })
                root_id = r["span_id"]
                tp = r["traceparent"]

                for step_name in ["VBA.Workbook_Open", "VBA.Range_Read",
                                  "VBA.FX_Conversion", "VBA.Range_Write_Consolidation"]:
                    rs = post({"action": "start_span", "name": step_name,
                               "kind": "internal", "traceparent": tp,
                               "attributes": {"finance.entity": sub["entity"]}})
                    post({"action": "end_span", "span_id": rs["span_id"]})

                rev_usd = sub["revenue"] * sub["fx_rate"]
                post({"action": "end_span", "span_id": root_id,
                      "attributes": {"finance.revenue_usd": round(rev_usd, 0)}})

            check(f"VBA.Macro_ConsolidatePL spans sent for {len(SUBSIDIARIES)} subsidiaries", True)
            post({"action": "metric_counter", "name": "vba.sheets_processed",
                  "value": len(SUBSIDIARIES), "attributes": {}})

        except Exception as exc:
            check("Sidecar payload simulation completed without error", False, str(exc))

        print("\n  Waiting 3s for OTLP export to Elastic...")
        time.sleep(3)
        check("Sidecar process still alive", sidecar_proc.poll() is None)

    if sidecar_proc.poll() is None:
        sidecar_proc.terminate()
        sidecar_proc.wait(timeout=5)

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
print(f"  Kibana -> APM -> {SVC}")
if failed:
    sys.exit(1)
