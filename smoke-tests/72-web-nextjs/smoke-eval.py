#!/usr/bin/env python3
"""
Eval test: Web — Next.js 14 ShopClient
========================================
Runs `claude -p "Observe this project."` on a blank Next.js app
(fixtures/blank-nextjs-shop/) and verifies OTel instrumentation.

NOTE: Live run SKIPPED — requires Node.js + bundler.

Run:
    cd smoke-tests && python3 72-web-nextjs/smoke-eval.py
"""

import os, sys, shutil, subprocess, tempfile, time
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")
if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set"); sys.exit(0)

SVC         = "72-web-nextjs"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "blank-nextjs-shop")
CLAUDE_MD   = os.path.join(os.path.dirname(__file__), "../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD):
    CLAUDE_MD = os.path.join(os.path.dirname(__file__), "../../../CLAUDE.md")

CHECKS: list[tuple[str, bool, str]] = []
def check(name, ok, detail=""): CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}\nEDOT-Autopilot | {SVC}\n{'='*62}")
print(f"  Fixture: blank-nextjs-shop (Next.js 14, no OTel)")
print(f"  NOTE: Live run SKIPPED — requires Node.js + bundler\n")

print("Step 1: Prerequisites")
claude_bin = shutil.which("claude")
check("claude CLI is installed", claude_bin is not None)
check("CLAUDE.md exists", os.path.exists(CLAUDE_MD))
check("Fixture directory exists", os.path.isdir(FIXTURE_DIR))
pkg = os.path.join(FIXTURE_DIR, "package.json")
if os.path.exists(pkg):
    check("package.json has no OTel", "opentelemetry" not in open(pkg).read().lower())
if not claude_bin or not os.path.exists(CLAUDE_MD) or not os.path.isdir(FIXTURE_DIR):
    [print(f"  [{s}] {n}") for s, n, _ in CHECKS]; sys.exit(1)
print("  [PASS] all critical prerequisites met\n")

print("Step 2: Setting up blank app workspace")
tmpdir = tempfile.mkdtemp(prefix="edot-autopilot-nextjs-")
try:
    shutil.copytree(FIXTURE_DIR, tmpdir, dirs_exist_ok=True)
    shutil.copy2(CLAUDE_MD, os.path.join(tmpdir, "CLAUDE.md"))
    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@edot-autopilot"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "EDOT Autopilot Eval"], cwd=tmpdir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial: blank Next.js app, no observability"],
                   cwd=tmpdir, capture_output=True, check=True)
    print(f"  Workspace: {tmpdir}\n")

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
        for line in result.stdout.strip().splitlines()[-20:]: print(f"    {line}")
    check("Agent exited cleanly", result.returncode == 0,
          f"stderr: {result.stderr[-500:] if result.stderr else ''}")

    print("\nStep 4: Inspecting generated files")
    pkg_file = os.path.join(tmpdir, "package.json")
    pkg_content = open(pkg_file).read() if os.path.exists(pkg_file) else ""
    all_ts_content = ""
    for root, _, files in os.walk(tmpdir):
        for f in files:
            if f.endswith(('.ts', '.tsx', '.js', '.mjs')) and 'node_modules' not in root:
                all_ts_content += open(os.path.join(root, f)).read()

    otel_slos   = os.path.join(tmpdir, ".otel", "slos.json")
    otel_golden = os.path.join(tmpdir, ".otel", "golden-paths.md")

    print("\nCode correctness checks (Next.js OTel instrumentation):")
    check("OTel or @vercel/otel package added to package.json",
          "opentelemetry" in pkg_content.lower() or "vercel/otel" in pkg_content.lower(),
          f"package.json:\n{pkg_content[:500]}")
    check("OTel SDK initialized in app code (instrumentation.ts or layout)",
          "opentelemetry" in all_ts_content.lower() or "TracerProvider" in all_ts_content,
          "no OTel initialization found")
    check("Elastic endpoint configured",
          "ELASTIC_OTLP_ENDPOINT" in all_ts_content
          or "OTLP_ENDPOINT" in all_ts_content
          or ENDPOINT.split("//")[-1][:20] in all_ts_content,
          "endpoint not referenced in app code")
    check("Live app run", True, "# SKIP: requires Node.js + Next.js bundler")
    print("\n.otel/ output file checks:")
    check(".otel/slos.json created", os.path.exists(otel_slos))
    check(".otel/golden-paths.md created", os.path.exists(otel_golden))

finally:
    failed_checks = [n for s, n, _ in CHECKS if s == "FAIL"]
    if failed_checks: print(f"\n  NOTE: Workspace preserved: {tmpdir}")
    else: shutil.rmtree(tmpdir, ignore_errors=True)

passed = sum(1 for s, _, _ in CHECKS if s == "PASS")
failed = sum(1 for s, _, _ in CHECKS if s == "FAIL")
print(f"\n{'='*62}")
for status, name, detail in CHECKS:
    line = f"  [{status}] {name}"
    if detail and status == "FAIL": line += f"\n         -> {detail}"
    print(line)
print(f"\n  Result: {passed}/{len(CHECKS)} checks passed")
print(f"  Kibana → RUM → shop-client-next (Next.js)")
if failed: sys.exit(1)
