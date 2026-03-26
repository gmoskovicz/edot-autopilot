#!/usr/bin/env python3
"""
E2E "Observe this project." — Tier D SAP ABAP Purchase Order
=============================================================
Runs `claude -p "Observe this project."` on a blank SAP ABAP report
(ZMM_CREATE_PO) that creates purchase orders via BAPI calls.
Because ABAP cannot link an OTel SDK, the agent must assign
Tier D (sidecar bridge) and:

  1. Copy otel-sidecar.py into the project directory
  2. Add HTTP POST calls to the ABAP source (or a wrapper script) so
     that ZMM_CREATE_PO, BAPI_PO_CREATE1, and
     BAPI_MATERIAL_AVAILABILITY spans are emitted via the sidecar API
  3. Create .otel/slos.json and .otel/golden-paths.md

Verification (after running claude -p):
  - otel-sidecar.py is present in the project
  - ZMM_CREATE_PO.abap or a helper contains HTTP / curl / cl_http_client
    calls targeting the sidecar
  - .otel/slos.json was created
  - Starting the sidecar and POSTing simulated payloads creates spans
    with correct names and SAP business attributes

Run:
    cd smoke-tests && python3 35-tier-d-sap-abap/smoke.py
"""

import os
import sys
import time
import json
import shutil
import subprocess
import tempfile
import random

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")

if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set")
    sys.exit(0)

SVC         = "35-tier-d-sap-abap"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-sap-abap")
SIDECAR_SRC = os.path.join(os.path.dirname(__file__), "../../otel-sidecar/otel-sidecar.py")

CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

SIDECAR_PORT = 19435

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))


print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Fixture: blank-sap-abap (no OTel, no sidecar)")
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

abap_path = os.path.join(FIXTURE_DIR, "ZMM_CREATE_PO.abap")
if os.path.exists(abap_path):
    abap_content = open(abap_path).read()
    check("Fixture ABAP has no sidecar calls yet",
          "otel-sidecar" not in abap_content.lower()
          and "cl_http_client" not in abap_content.lower()
          and "9411" not in abap_content,
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
print("Step 2: Setting up blank SAP ABAP workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-abap-")
try:
    for fname in os.listdir(FIXTURE_DIR):
        src = os.path.join(FIXTURE_DIR, fname)
        dst = os.path.join(tmpdir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, dst)

    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))

    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@edot-autopilot"], cwd=tmpdir,
                   capture_output=True)
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot E2E"], cwd=tmpdir,
                   capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial: blank SAP ABAP, no observability"],
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

    all_text = "\n".join(
        open(os.path.join(tmpdir, f)).read()
        for f in os.listdir(tmpdir)
        if os.path.isfile(os.path.join(tmpdir, f))
        and not f.startswith(".")
        and f != "CLAUDE.md"
    )

    otel_slos   = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")
    sidecar_path = os.path.join(tmpdir, "otel-sidecar.py")

    print("\nTier D (sidecar bridge) checks:")

    check("otel-sidecar.py added to project",
          os.path.exists(sidecar_path)
          or any("otel-sidecar" in f for f in new_files),
          f"new files: {new_files}")

    has_http = any(kw in all_text.lower() for kw in [
        "cl_http_client", "http_post", "curl ", "requests.post",
        "9411", "otel-sidecar", "start_span", "end_span", "action",
    ])
    check("ABAP or helper contains HTTP sidecar calls",
          has_http,
          "no CL_HTTP_CLIENT/curl/sidecar references found in project files")

    has_span_names = any(name in all_text for name in [
        "ZMM_CREATE_PO", "BAPI_PO_CREATE1", "BAPI_MATERIAL_AVAILABILITY",
        "ABAP.ZMM_CREATE_PO", "ABAP.BAPI_PO_CREATE1",
    ])
    check("Correct SAP ABAP span names referenced",
          has_span_names,
          "expected ZMM_CREATE_PO / BAPI_PO_CREATE1 / BAPI_MATERIAL_AVAILABILITY")

    has_biz_attrs = any(attr in all_text for attr in [
        "sap.program", "sap.po_number", "sap.vendor", "sap.material",
        "sap.plant", "sap.po_value_eur", "sap.bapi",
    ])
    check("Business span attributes referenced (sap.*)",
          has_biz_attrs,
          "no sap.* attribute names found")

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
    print("\nStep 5: Starting otel-sidecar.py and sending simulated SAP ABAP payloads")

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
        print("\nStep 6: Sending simulated SAP ABAP span payloads via HTTP POST")

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

        PURCHASE_ORDERS = [
            {"vendor": "V-10023", "material": "MAT-5001", "qty": 500,
             "unit_price": 12.50, "plant": "1000"},
            {"vendor": "V-10087", "material": "MAT-3214", "qty": 200,
             "unit_price": 89.99, "plant": "1000"},
            {"vendor": "V-10055", "material": "MAT-9981", "qty": 1000,
             "unit_price": 3.75,  "plant": "2000"},
        ]

        try:
            for po in PURCHASE_ORDERS:
                po_number = f"4500{random.randint(100000, 999999)}"
                total_val = round(po["qty"] * po["unit_price"], 2)

                # Root ZMM_CREATE_PO span
                r = post({
                    "action": "start_span",
                    "name": "ABAP.ZMM_CREATE_PO",
                    "kind": "internal",
                    "attributes": {
                        "sap.program":     "ZMM_CREATE_PO",
                        "sap.transaction": "ME21N",
                        "sap.vendor":      po["vendor"],
                        "sap.material":    po["material"],
                        "sap.plant":       po["plant"],
                        "sap.quantity":    po["qty"],
                    },
                })
                root_id = r["span_id"]
                root_tp = r["traceparent"]
                check(f"start_span ABAP.ZMM_CREATE_PO vendor={po['vendor']} → ok",
                      r.get("ok") is True, str(r))

                # BAPI_PO_CREATE1
                r2 = post({
                    "action": "start_span",
                    "name": "ABAP.BAPI_PO_CREATE1",
                    "kind": "client",
                    "traceparent": root_tp,
                    "attributes": {
                        "sap.bapi":     "BAPI_PO_CREATE1",
                        "sap.vendor":   po["vendor"],
                        "sap.doc_type": "NB",
                    },
                })
                bapi_id = r2["span_id"]
                post({"action": "end_span", "span_id": bapi_id,
                      "attributes": {
                          "sap.po_number":   po_number,
                          "sap.po_value_eur": total_val,
                      }})
                check("ABAP.BAPI_PO_CREATE1 span round-trip", r2.get("ok") is True, str(r2))

                # Log BAPI execution
                post({
                    "action": "log",
                    "body": "BAPI_PO_CREATE1 executed",
                    "severity": "INFO",
                    "traceparent": root_tp,
                    "attributes": {
                        "sap.bapi":        "BAPI_PO_CREATE1",
                        "sap.po_number":   po_number,
                        "sap.vendor":      po["vendor"],
                        "sap.po_value_eur": total_val,
                    },
                })

                # BAPI_MATERIAL_AVAILABILITY
                available = random.choice([True, True, True, False])
                r3 = post({
                    "action": "start_span",
                    "name": "ABAP.BAPI_MATERIAL_AVAILABILITY",
                    "kind": "client",
                    "traceparent": root_tp,
                    "attributes": {
                        "sap.bapi":     "BAPI_MATERIAL_AVAILABILITY",
                        "sap.material": po["material"],
                        "sap.plant":    po["plant"],
                    },
                })
                avail_id = r3["span_id"]
                avail_attrs = {"sap.material_available": available}
                if not available:
                    avail_attrs["sap.backorder_qty"] = po["qty"] // 2
                post({"action": "end_span", "span_id": avail_id, "attributes": avail_attrs})
                check("ABAP.BAPI_MATERIAL_AVAILABILITY span round-trip",
                      r3.get("ok") is True, str(r3))

                # Metrics
                post({"action": "metric_counter", "name": "sap.po_created",
                      "value": 1,
                      "attributes": {"sap.plant": po["plant"], "sap.vendor": po["vendor"]}})
                post({"action": "metric_histogram", "name": "sap.po_value_eur",
                      "value": total_val,
                      "attributes": {"sap.plant": po["plant"]}})

                # End root span
                post({"action": "end_span", "span_id": root_id,
                      "attributes": {
                          "sap.po_number":   po_number,
                          "sap.po_value_eur": total_val,
                      }})

            check("All SAP PO spans completed successfully", True)

        except Exception as exc:
            check("Sidecar payload simulation completed without error", False, str(exc))

        print("\n  Waiting 5s for BatchSpanProcessor to flush to Elastic...")
        time.sleep(5)

        check("Sidecar process still alive after payload simulation",
              sidecar_proc.poll() is None,
              "sidecar died unexpectedly")

        # ── Step 7: Verify spans actually landed in Elastic ───────────────────
        print("\nStep 7: Verifying spans reached Elastic")
        ES_URL = os.environ.get("ELASTICSEARCH_URL", "").rstrip("/")
        ES_KEY = os.environ.get("ELASTICSEARCH_API_KEY", "")
        if not ES_URL or not ES_KEY:
            print("  [SKIP] ELASTICSEARCH_URL / ELASTICSEARCH_API_KEY not set — skipping ES|QL check")
        else:
            import json as _json
            span_confirmed = False
            for attempt in range(3):
                try:
                    body = _json.dumps({"query": (
                        f'FROM traces-generic.otel-default,traces-apm* '
                        f'| WHERE service.name == "{SVC}" '
                        f'| LIMIT 1'
                    )}).encode()
                    req = urllib.request.Request(
                        f"{ES_URL}/_query",
                        data=body,
                        headers={
                            "Authorization": f"ApiKey {ES_KEY}",
                            "Content-Type": "application/json",
                        },
                        method="POST",
                    )
                    resp = urllib.request.urlopen(req, timeout=10)
                    result = _json.loads(resp.read())
                    if result.get("values") and len(result["values"]) > 0:
                        span_confirmed = True
                        break
                    print(f"  ES|QL attempt {attempt+1}/3: no spans yet, retrying in 5s...")
                    time.sleep(5)
                except Exception as e:
                    print(f"  ES|QL attempt {attempt+1}/3 failed: {e}")
                    time.sleep(5)
            check("Spans confirmed in Elastic (ES|QL)", span_confirmed,
                  f"service '{SVC}' not found in traces-generic.otel-default after 3 attempts")

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
