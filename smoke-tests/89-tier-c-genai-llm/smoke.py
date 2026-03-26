#!/usr/bin/env python3
"""
Smoke test 89 — Tier C: Gen-AI / LLM observability (gen_ai.* semconv)
Runs app.py and verifies it exits cleanly, emitting spans for all three providers.
"""
import subprocess
import sys
import os

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if detail and not ok:
        print(f"        -> {detail[:400]}")


print("\n" + "=" * 62)
print("Smoke test 89 — Tier C: Gen-AI / LLM (gen_ai.* semconv)")
print("=" * 62)

result = subprocess.run(
    [sys.executable, os.path.join(os.path.dirname(__file__), "app.py")],
    capture_output=True,
    text=True,
)

check("app.py exits cleanly", result.returncode == 0,
      f"stderr: {result.stderr[-400:]}")
check("OpenAI provider instrumented",
      "openai" in result.stdout, result.stdout[-200:])
check("Anthropic provider instrumented",
      "anthropic" in result.stdout, result.stdout[-200:])
check("AWS Bedrock provider instrumented",
      "bedrock" in result.stdout or "amazon.nova" in result.stdout,
      result.stdout[-200:])
check("All 6 LLM calls completed",
      "6 LLM calls" in result.stdout, result.stdout[-200:])

passed = sum(1 for s, _, _ in CHECKS if s == "PASS")
failed = sum(1 for s, _, _ in CHECKS if s == "FAIL")

print(f"\n  Result: {passed}/{len(CHECKS)} checks passed")
if failed:
    print(f"  FAIL: {failed} check(s) failed")
    sys.exit(1)
else:
    print("  PASS: All checks passed")
