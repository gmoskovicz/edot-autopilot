#!/usr/bin/env python3
"""
E2E "Observe this project." — Tier D MATLAB Predictive Maintenance
===================================================================
Runs `claude -p "Observe this project."` on a blank MATLAB signal
processing script.  Because MATLAB has no OTel SDK, the agent must
assign Tier D (sidecar bridge) and instrument script.m with HTTP calls.

Run:
    cd smoke-tests && python3 39-tier-d-matlab/smoke.py
"""

import os, sys, time, json, shutil, subprocess, tempfile
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")

if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set")
    sys.exit(0)

SVC         = "39-tier-d-matlab"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-matlab")
SIDECAR_SRC = os.path.join(os.path.dirname(__file__), "../../otel-sidecar/otel-sidecar.py")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")
SIDECAR_PORT = 19439

CHECKS: list[tuple[str, bool, str]] = []

def check(name, ok, detail=""):
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}\nEDOT-Autopilot | {SVC}\n{'='*62}")
print("  Fixture: blank-matlab (no OTel, no sidecar)\n")

print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
check("claude CLI is installed", claude_bin is not None)
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD))
check("Fixture directory exists", os.path.isdir(FIXTURE_DIR))
check("otel-sidecar.py source exists", os.path.exists(SIDECAR_SRC))
script_path = os.path.join(FIXTURE_DIR, "script.m")
if os.path.exists(script_path):
    content = open(script_path).read()
    check("Fixture has no sidecar calls yet",
          "sidecar" not in content.lower() and "otel" not in content.lower())
if any(s == "FAIL" for s, _, _ in CHECKS):
    for s, n, d in CHECKS:
        print(f"  [{s}] {n}" + (f"\n         -> {d}" if d and s == "FAIL" else ""))
    sys.exit(1)
print("  [PASS] all prerequisites met\n")

print("Step 2: Setting up blank MATLAB workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-matlab-")
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
    subprocess.run(["git", "commit", "-m", "initial: blank MATLAB, no observability"],
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
    check("MATLAB or helper contains HTTP sidecar calls",
          any(kw in all_text.lower() for kw in
              ["webwrite", "urlread", "otel-sidecar", "start_span", "sidecar", "curl"]))
    check("Correct MATLAB span names referenced",
          any(n in all_text for n in
              ["predictive_maintenance", "load_sensor_data", "bearing_fault_detector",
               "MATLAB.fft", "MATLAB.predictive"]))
    check("Business span attributes referenced (matlab.*/signal.*)",
          any(a in all_text for a in
              ["matlab.script", "sensor.id", "signal.rms_g", "anomaly.confidence",
               "matlab.function"]))

    print("\n.otel/ output file checks:")
    check(".otel/slos.json created", os.path.exists(otel_slos))
    if os.path.exists(otel_slos):
        try:
            check(".otel/slos.json is valid JSON", isinstance(json.load(open(otel_slos)), (list, dict)))
        except json.JSONDecodeError as e:
            check(".otel/slos.json is valid JSON", False, str(e))
    check(".otel/golden-paths.md created", os.path.exists(otel_golden))

    print("\nStep 5: Starting otel-sidecar.py and sending simulated MATLAB payloads")
    sidecar_py = sidecar_path if os.path.exists(sidecar_path) else SIDECAR_SRC
    sidecar_env = os.environ.copy()
    sidecar_env.update({"OTEL_SERVICE_NAME": SVC, "ELASTIC_OTLP_ENDPOINT": ENDPOINT,
                         "ELASTIC_API_KEY": API_KEY, "OTEL_DEPLOYMENT_ENVIRONMENT": "smoke-test",
                         "SIDECAR_PORT": str(SIDECAR_PORT)})
    sidecar_proc = subprocess.Popen(
        [sys.executable, sidecar_py], env=sidecar_env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    import urllib.request
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

        SENSORS = [
            {"sensor_id": "VIB-PUMP-01",  "asset": "Centrifugal Pump A", "sample_hz": 25600},
            {"sensor_id": "VIB-MOTOR-03", "asset": "Drive Motor #3",     "sample_hz": 51200},
        ]
        try:
            for sensor in SENSORS:
                r = post({"action": "start_span", "name": "MATLAB.predictive_maintenance",
                           "kind": "internal",
                           "attributes": {"matlab.script": "run_vibration_analysis.m",
                                          "sensor.id": sensor["sensor_id"],
                                          "sensor.asset": sensor["asset"],
                                          "signal.sample_hz": sensor["sample_hz"]}})
                root_id = r["span_id"]; tp = r["traceparent"]
                check(f"start_span MATLAB.predictive_maintenance ({sensor['sensor_id']}) → ok",
                      r.get("ok") is True, str(r))
                for step in ["MATLAB.load_sensor_data", "MATLAB.fft", "MATLAB.bearing_fault_detector"]:
                    rs = post({"action": "start_span", "name": step, "kind": "internal",
                               "traceparent": tp, "attributes": {"sensor.id": sensor["sensor_id"]}})
                    post({"action": "end_span", "span_id": rs["span_id"],
                          "attributes": {"signal.dominant_freq_hz": 88.0}})
                post({"action": "end_span", "span_id": root_id,
                      "attributes": {"signal.rms_g": 1.8, "anomaly.confidence": 0.45,
                                     "anomaly.detected": False}})
            check(f"MATLAB span round-trips completed for {len(SENSORS)} sensors", True)
            post({"action": "metric_counter", "name": "matlab.sensors_analyzed",
                  "value": len(SENSORS), "attributes": {}})
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
