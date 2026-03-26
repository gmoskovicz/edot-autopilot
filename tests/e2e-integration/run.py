#!/usr/bin/env python3
"""
E2E Integration Test — Claude instruments a blank app; spans validated via local OTel Collector.

Flow:
  1. Start a local OTel Collector (Docker) with a file exporter — no Elastic needed
  2. Copy the blank fraud-detection fixture to a temp workspace + inject CLAUDE.md
  3. Run: claude -p "Observe this project. My Elastic endpoint: http://localhost:4318 ..."
  4. Install whatever packages Claude added to requirements.txt
  5. Start the instrumented app; override OTEL env vars to point at local collector
  6. Generate real HTTP traffic
  7. Parse collector output and assert spans carry business attributes

Requires:
  - docker (with compose plugin)
  - claude CLI (npm install -g @anthropic-ai/claude-code)
  - ANTHROPIC_API_KEY in environment
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO_ROOT   = Path(__file__).resolve().parents[2]
HERE        = Path(__file__).resolve().parent
FIXTURE_DIR = REPO_ROOT / "smoke-tests" / "01-tier-a-python" / "fixtures" / "blank-fraud-detection"
CLAUDE_MD   = REPO_ROOT / "CLAUDE.md"
OUTPUT_DIR  = HERE / "output"
TRACES_FILE = OUTPUT_DIR / "traces.jsonl"

COLLECTOR_PORT = 4318
APP_PORT       = 15002

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if detail and not ok:
        print(f"        -> {detail[:400]}")


def post_json(path: str, body: dict) -> int:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{APP_PORT}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def get_status(path: str) -> int:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{APP_PORT}{path}", timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


print(f"\n{'='*64}")
print("EDOT Autopilot | E2E Integration Test")
print("Claude instruments a blank app → local collector → span validation")
print(f"{'='*64}\n")


# ── Step 0: Prerequisites ─────────────────────────────────────────────────────
print("Step 0: Prerequisites")

claude_bin = shutil.which("claude")
check("claude CLI available", claude_bin is not None,
      "install: npm install -g @anthropic-ai/claude-code")
check("ANTHROPIC_API_KEY set", bool(os.environ.get("ANTHROPIC_API_KEY")),
      "export ANTHROPIC_API_KEY=your-key")
check("CLAUDE.md exists",    CLAUDE_MD.exists(),    str(CLAUDE_MD))
check("Blank fixture exists", FIXTURE_DIR.is_dir(), str(FIXTURE_DIR))
check("Docker available",    shutil.which("docker") is not None)
check("Fixture has no OTel", not any(
    "opentelemetry" in (FIXTURE_DIR / f).read_text()
    for f in ["app.py", "requirements.txt"]
    if (FIXTURE_DIR / f).exists()
), "fixture already contains opentelemetry — test is invalid")

if any(s == "FAIL" for s, _, _ in CHECKS):
    print("\nPrerequisites failed — cannot continue.")
    sys.exit(2)
print()


# ── Step 1: Start local OTel Collector ────────────────────────────────────────
print("Step 1: Starting local OTel Collector")

OUTPUT_DIR.mkdir(exist_ok=True)
TRACES_FILE.unlink(missing_ok=True)

subprocess.run(
    ["docker", "compose", "up", "-d", "--wait"],
    cwd=HERE, check=True, capture_output=True,
)
check("OTel Collector started and healthy", True)
time.sleep(2)
print()


# ── Main test (in try/finally to ensure cleanup) ──────────────────────────────
tmpdir: Path | None = None
app_proc = None

try:
    # ── Step 2: Set up blank workspace ────────────────────────────────────────
    print("Step 2: Setting up blank app workspace")

    tmpdir = Path(tempfile.mkdtemp(prefix="edot-e2e-"))
    for f in FIXTURE_DIR.iterdir():
        if f.is_file():
            shutil.copy2(f, tmpdir / f.name)
    shutil.copy2(CLAUDE_MD, tmpdir / "CLAUDE.md")

    for cmd in [
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@edot-autopilot"],
        ["git", "config", "user.name", "EDOT E2E"],
        ["git", "add", "."],
        ["git", "commit", "-q", "-m", "initial: blank app, no observability"],
    ]:
        subprocess.run(cmd, cwd=tmpdir, check=True, capture_output=True)

    check("Workspace created", True, str(tmpdir))
    print(f"  Files: {sorted(f.name for f in tmpdir.iterdir())}\n")


    # ── Step 3: Run "Observe this project." ───────────────────────────────────
    print("Step 3: Running claude -p 'Observe this project.' (takes 2–5 min)...")

    observe_prompt = (
        "Observe this project.\n"
        f"My Elastic endpoint: http://localhost:{COLLECTOR_PORT}\n"
        "My Elastic API key: e2e-test-key"
    )

    t0 = time.time()
    result = subprocess.run(
        [
            claude_bin,
            "--dangerously-skip-permissions",
            "-p", observe_prompt,
            "--model", "claude-sonnet-4-6",
            "--max-budget-usd", "3.00",
        ],
        cwd=tmpdir,
        capture_output=True, text=True,
        timeout=600,
    )
    elapsed = time.time() - t0
    print(f"  Agent finished in {elapsed:.0f}s (exit {result.returncode})")
    for line in result.stdout.strip().splitlines()[-10:]:
        print(f"    {line}")

    check("claude exited cleanly", result.returncode == 0,
          f"stderr: {result.stderr[-500:]}")

    req_file = tmpdir / "requirements.txt"
    app_file = tmpdir / "app.py"
    otel_dir = tmpdir / ".otel"

    req_content = req_file.read_text() if req_file.exists() else ""
    app_content = app_file.read_text() if app_file.exists() else ""

    print("\nGenerated output checks:")
    check("requirements.txt includes opentelemetry packages",
          "opentelemetry" in req_content, f"requirements.txt:\n{req_content[:400]}")
    check("app.py instrumented",
          any(k in app_content for k in
              ["opentelemetry", "TracerProvider", "set_attribute", "FastAPIInstrumentor"]),
          app_content[:300])
    check(".otel/ directory created", otel_dir.is_dir())
    check(".otel/golden-paths.md created", (otel_dir / "golden-paths.md").exists())
    check("Business attributes added to app.py",
          any(k in app_content for k in [
              "fraud.score", "fraud_score", "fraud.decision",
              "customer.tier", "customer_tier",
              "order.total", "total_usd", "payment.status",
          ]),
          "no business enrichment attributes found in app.py")
    print()


    # ── Step 4: Install generated requirements ────────────────────────────────
    print("Step 4: Installing generated requirements")

    pip = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-r", str(req_file),
         "--no-warn-script-location"],
        capture_output=True, text=True,
    )
    check("pip install succeeded", pip.returncode == 0, pip.stderr[-400:])
    print()


    # ── Step 5: Start instrumented app ────────────────────────────────────────
    print("Step 5: Starting instrumented app")

    env = os.environ.copy()
    env.update({
        "PORT":                          str(APP_PORT),
        "OTEL_SERVICE_NAME":             "e2e-inttest",
        # Override whatever endpoint Claude configured — always point at local collector
        "OTEL_EXPORTER_OTLP_ENDPOINT":   f"http://localhost:{COLLECTOR_PORT}",
        "OTEL_EXPORTER_OTLP_PROTOCOL":   "http/protobuf",
        "OTEL_METRICS_EXPORTER":         "otlp",
        "OTEL_LOGS_EXPORTER":            "otlp",
        "OTEL_DEPLOYMENT_ENVIRONMENT":   "e2e-test",
    })

    app_proc = subprocess.Popen(
        [sys.executable, str(app_file)],
        cwd=tmpdir, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    started = False
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{APP_PORT}/health", timeout=1)
            started = True
            break
        except Exception:
            if app_proc.poll() is not None:
                break
            time.sleep(1)

    if not started and app_proc.poll() is not None:
        out, err = app_proc.stdout.read(), app_proc.stderr.read()
        check("App started", False,
              f"exited {app_proc.returncode}\nstdout: {out[-300:]}\nstderr: {err[-300:]}")
    else:
        check("App started and /health responds", started)
    print()


    # ── Step 6: Generate real traffic ─────────────────────────────────────────
    print("Step 6: Generating traffic")

    if started:
        s = post_json("/orders", {
            "customer_id": "cust_e2e_enterprise",
            "customer_tier": "enterprise",
            "items": [{"name": "Widget Pro", "price_usd": 49.99, "qty": 2}],
        })
        check("POST /orders → 201 or 402 (fraud block ok)", s in (201, 402), f"got {s}")

        s = get_status("/orders/nonexistent-order-id")
        check("GET /orders/<missing> → 404", s == 404, f"got {s}")

        check("App still running after requests", app_proc.poll() is None)

        print("  Waiting 10s for BatchSpanProcessor to flush...")
        time.sleep(10)

    print()


    # ── Step 7: Validate collector output ─────────────────────────────────────
    print("Step 7: Validating spans in collector output")

    if not TRACES_FILE.exists() or TRACES_FILE.stat().st_size == 0:
        check("Collector received spans", False, f"{TRACES_FILE} missing or empty")
    else:
        spans_by_service: dict[str, list] = defaultdict(list)
        for line in TRACES_FILE.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                export = json.loads(line)
            except json.JSONDecodeError:
                continue
            for rs in export.get("resourceSpans", []):
                svc = None
                for a in rs.get("resource", {}).get("attributes", []):
                    if a["key"] == "service.name":
                        v = a.get("value", {})
                        svc = (v.get("stringValue")
                               or str(next(iter(v.values()), "")))
                        break
                for ss in rs.get("scopeSpans", []):
                    for span in ss.get("spans", []):
                        spans_by_service[svc].append(span)

        total_spans = sum(len(v) for v in spans_by_service.values())
        print(f"  Services seen: {sorted(s for s in spans_by_service if s)}")
        print(f"  Total spans:   {total_spans}")

        check("At least one span received by collector", total_spans > 0)

        e2e_spans = spans_by_service.get("e2e-inttest", [])
        check("e2e-inttest service emitted spans", len(e2e_spans) > 0,
              f"services: {sorted(s for s in spans_by_service if s)}")

        all_attr_keys: set[str] = set()
        for span in e2e_spans:
            for a in span.get("attributes", []):
                all_attr_keys.add(a["key"])

        BUSINESS_SIGNALS = {
            "fraud.score", "fraud_score", "fraud.decision",
            "customer.tier", "customer_tier",
            "order.total", "order.total_usd", "total_usd",
            "payment.status", "order.id",
        }
        found_business = BUSINESS_SIGNALS & all_attr_keys
        check("Business attributes present on spans", bool(found_business),
              f"all attr keys: {sorted(all_attr_keys)[:25]}")
        if found_business:
            print(f"  Business attrs: {sorted(found_business)}")

        DEPRECATED = {"http.method", "http.url", "http.status_code", "db.statement"}
        deprecated_found = DEPRECATED & all_attr_keys
        check("No deprecated semconv attributes", not deprecated_found,
              f"found: {deprecated_found}")


except Exception as exc:
    check("No unexpected exception during test", False, str(exc))
    import traceback; traceback.print_exc()

finally:
    if app_proc and app_proc.poll() is None:
        app_proc.terminate()
        app_proc.wait(timeout=5)

    subprocess.run(
        ["docker", "compose", "down", "--volumes", "--remove-orphans"],
        cwd=HERE, capture_output=True,
    )

    failed = [n for s, n, _ in CHECKS if s == "FAIL"]
    if failed and tmpdir:
        print(f"\n  Workspace preserved for debugging: {tmpdir}")
    elif tmpdir:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Summary ───────────────────────────────────────────────────────────────────
passed = sum(1 for s, _, _ in CHECKS if s == "PASS")
failed = sum(1 for s, _, _ in CHECKS if s == "FAIL")

print(f"\n{'='*64}")
print(f"Result: {passed}/{len(CHECKS)} checks passed")
if failed:
    print(f"FAIL: {failed} check(s) failed")
    sys.exit(1)
else:
    print("PASS: All E2E checks passed ✓")
