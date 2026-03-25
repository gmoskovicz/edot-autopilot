#!/usr/bin/env python3
"""
E2E "Observe this project." — Tier D AWK ETL Access Log Parser
===============================================================
Runs `claude -p "Observe this project."` on a blank AWK ETL script.
AWK has no OTel SDK; agent must assign Tier D sidecar bridge.

Run:
    cd smoke-tests && python3 43-tier-d-awk-etl/smoke.py
"""

import os, sys, time, json, shutil, subprocess, tempfile, urllib.request
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")

if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set"); sys.exit(0)

SVC         = "43-tier-d-awk-etl"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-awk-etl")
SIDECAR_SRC = os.path.join(os.path.dirname(__file__), "../../otel-sidecar/otel-sidecar.py")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")
SIDECAR_PORT = 19443

CHECKS: list[tuple[str, bool, str]] = []
def check(name, ok, detail=""):
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}\nEDOT-Autopilot | {SVC}\n{'='*62}")
print("  Fixture: blank-awk-etl (no OTel, no sidecar)\n")

print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
check("claude CLI is installed", claude_bin is not None)
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD))
check("Fixture directory exists", os.path.isdir(FIXTURE_DIR))
check("otel-sidecar.py source exists", os.path.exists(SIDECAR_SRC))
awk_path = os.path.join(FIXTURE_DIR, "parse_access_logs.awk")
if os.path.exists(awk_path):
    content = open(awk_path).read()
    check("Fixture AWK has no sidecar calls yet",
          "sidecar" not in content.lower() and "otel" not in content.lower())
if any(s == "FAIL" for s, _, _ in CHECKS):
    for s, n, d in CHECKS:
        print(f"  [{s}] {n}" + (f"\n         -> {d}" if d and s == "FAIL" else ""))
    sys.exit(1)
print("  [PASS] all prerequisites met\n")

print("Step 2: Setting up blank AWK workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-awk-")
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
    subprocess.run(["git", "commit", "-m", "initial: blank AWK, no observability"],
                   cwd=tmpdir, capture_output=True, check=True)
    check("Temp workspace created", True, tmpdir)
    print(f"  Workspace: {tmpdir}\n")

    print("Step 3: Running claude -p 'Observe this project.' ...")
    observe_prompt = f"Observe this project.\nMy Elastic endpoint: {ENDPOINT}\nMy Elastic API key: {API_KEY}"
    t0 = time.time()
    result = subprocess.run(
        [claude_bin, "--dangerously-skip-permissions", "-p", observe_prompt,
         "--model", "claude-sonnet-4-6", "--max-budget-usd", "2.00"],
        cwd=tmpdir, capture_output=True, text=True, timeout=600)
    elapsed = time.time() - t0
    print(f"  Agent finished in {elapsed:.0f}s (exit code {result.returncode})")
    if result.stdout:
        for line in result.stdout.strip().splitlines()[-20:]:
            print(f"    {line}")
    check("Agent exited cleanly", result.returncode == 0,
          f"stderr: {result.stderr[-500:] if result.stderr else ''}")

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
    check("AWK or helper contains HTTP sidecar calls",
          any(kw in all_text.lower() for kw in
              ["curl", "wget", "otel-sidecar", "start_span", "sidecar", "http"]))
    check("Correct AWK span names referenced",
          any(n in all_text for n in
              ["etl_pipeline", "parse_log", "aggregate_by_endpoint",
               "write_summary_csv", "awk.etl", "access_log"]))
    check("Business span attributes referenced (awk.*/http.*/etl.*)",
          any(a in all_text for a in
              ["awk.script", "http.method", "http.status", "log.source",
               "etl.records_processed", "log.endpoint"]))

    print("\n.otel/ output file checks:")
    check(".otel/slos.json created", os.path.exists(otel_slos))
    if os.path.exists(otel_slos):
        try:
            check(".otel/slos.json is valid JSON", isinstance(json.load(open(otel_slos)), (list, dict)))
        except json.JSONDecodeError as e:
            check(".otel/slos.json is valid JSON", False, str(e))
    check(".otel/golden-paths.md created", os.path.exists(otel_golden))

    print("\nStep 5: Starting otel-sidecar.py and sending simulated AWK ETL payloads")
    sidecar_py = sidecar_path if os.path.exists(sidecar_path) else SIDECAR_SRC
    sidecar_env = os.environ.copy()
    sidecar_env.update({"OTEL_SERVICE_NAME": SVC, "ELASTIC_OTLP_ENDPOINT": ENDPOINT,
                         "ELASTIC_API_KEY": API_KEY, "OTEL_DEPLOYMENT_ENVIRONMENT": "smoke-test",
                         "SIDECAR_PORT": str(SIDECAR_PORT)})
    sidecar_proc = subprocess.Popen(
        [sys.executable, sidecar_py], env=sidecar_env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    sidecar_up = False
    for _ in range(30):
        try:
            resp = urllib.request.urlopen(urllib.request.Request(
                f"http://127.0.0.1:{SIDECAR_PORT}/",
                data=b'{"action":"health"}',
                headers={"Content-Type": "application/json"}, method="POST"), timeout=1)
            if resp.status == 200:
                sidecar_up = True; break
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

        LOG_BATCHES = [
            {"source": "/var/log/nginx/access.log", "records": 52341, "date": "2024-01-15"},
            {"source": "/var/log/apache2/access.log", "records": 18920, "date": "2024-01-15"},
        ]
        try:
            for batch in LOG_BATCHES:
                r = post({"action": "start_span", "name": "awk.etl_pipeline",
                           "kind": "internal",
                           "attributes": {"awk.script": "parse_access_logs.awk",
                                          "log.source": batch["source"],
                                          "etl.date": batch["date"]}})
                root_id = r["span_id"]; tp = r["traceparent"]
                check(f"start_span awk.etl_pipeline ({batch['source']}) → ok",
                      r.get("ok") is True, str(r))
                for step in ["awk.parse_log", "awk.aggregate_by_endpoint", "awk.write_summary_csv"]:
                    rs = post({"action": "start_span", "name": step,
                               "kind": "internal",
                               "traceparent": tp,
                               "attributes": {"log.source": batch["source"]}})
                    post({"action": "end_span", "span_id": rs["span_id"],
                          "attributes": {"etl.records_processed": batch["records"]}})
                post({"action": "end_span", "span_id": root_id,
                      "attributes": {"etl.records_processed": batch["records"],
                                     "http.status_200_count": 41073,
                                     "http.status_4xx_count": 892}})
            check(f"AWK ETL pipeline spans sent for {len(LOG_BATCHES)} batches", True)
            post({"action": "metric_counter", "name": "awk.log_lines_parsed",
                  "value": sum(b["records"] for b in LOG_BATCHES), "attributes": {}})
        except Exception as exc:
            check("Sidecar payload simulation completed without error", False, str(exc))

        print("\n  Waiting 3s for OTLP export to Elastic...")
        time.sleep(3)
        check("Sidecar process still alive", sidecar_proc.poll() is None)

    if sidecar_proc.poll() is None:
        sidecar_proc.terminate(); sidecar_proc.wait(timeout=5)

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
