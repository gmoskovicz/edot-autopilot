#!/usr/bin/env python3
"""
otel-contracts — Telemetry coverage-as-code for OpenTelemetry spans.

Validates that instrumented source files satisfy the attribute contracts
declared in .otel/contracts.yaml, and detects drift when contracted files
are modified without updating span attributes.

Usage:
  python otel-contracts.py validate                    # check all contracts
  python otel-contracts.py validate --id create-order  # check one contract
  python otel-contracts.py drift                       # check staged changes (pre-commit)
  python otel-contracts.py drift --base HEAD~1         # check against a commit
  python otel-contracts.py report                      # print coverage summary

Exit codes: 0 = pass, 1 = violations found, 2 = configuration error
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ── YAML loading ──────────────────────────────────────────────────────────────

def load_yaml(path: str) -> dict:
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        sys.exit(
            "otel-contracts requires PyYAML: pip install pyyaml\n"
            "Or install the full OTel stack: pip install opentelemetry-distro"
        )
    except FileNotFoundError:
        sys.exit(
            f"Contracts file not found: {path}\n"
            "Generate one with EDOT Autopilot: 'Observe this project.'"
        )


# ── Per-language span and attribute patterns ──────────────────────────────────
#
# Each template uses a {name} or {key} placeholder that is replaced with a
# re.escape'd literal before matching. Patterns are applied with re.IGNORECASE.

SPAN_PATTERNS: dict[str, list[str]] = {
    ".py":   [r'start_as_current_span\s*\(\s*["\']({name})["\']',
              r'start_span\s*\(\s*["\']({name})["\']'],
    ".js":   [r'startActiveSpan\s*\(\s*["\']({name})["\']',
              r'startSpan\s*\(\s*["\']({name})["\']'],
    ".ts":   [r'startActiveSpan\s*\(\s*["\']({name})["\']',
              r'startSpan\s*\(\s*["\']({name})["\']'],
    ".java": [r'spanBuilder\s*\(\s*"({name})"'],
    ".go":   [r'tracer\.Start\s*\([^,\n]+,\s*"({name})"'],
    ".rb":   [r'in_span\s*\(\s*["\']({name})["\']',
              r'start_span\s*\(\s*["\']({name})["\']'],
    ".php":  [r'startSpan\s*\(\s*["\']({name})["\']'],
    ".cs":   [r'StartActivity\s*\(\s*["\']({name})["\']',
              r'StartSpan\s*\(\s*["\']({name})["\']'],
}

ATTR_PATTERNS: dict[str, list[str]] = {
    ".py":   [r'set_attribute\s*\(\s*["\']({key})["\']'],
    ".js":   [r'setAttribute\s*\(\s*["\']({key})["\']'],
    ".ts":   [r'setAttribute\s*\(\s*["\']({key})["\']'],
    ".java": [r'setAttribute\s*\(\s*["\']({key})["\']',
              r'AttributeKey\.\w+Key\s*\(\s*"({key})"'],
    ".go":   [r'attribute\.\w+\s*\(\s*"({key})"'],
    ".rb":   [r'set_attribute\s*\(\s*["\']({key})["\']'],
    ".php":  [r'setAttribute\s*\(\s*["\']({key})["\']'],
    ".cs":   [r'SetTag\s*\(\s*["\']({key})["\']',
              r'SetAttribute\s*\(\s*["\']({key})["\']'],
    # Tier D — sidecar HTTP callers; search for the key string in POST body JSON
    ".sh":   [r'"({key})"\s*:'],
    ".bash": [r'"({key})"\s*:'],
    ".pl":   [r'({key})\s*=>',   r'"({key})"\s*:'],
    ".pm":   [r'({key})\s*=>',   r'"({key})"\s*:'],
    ".ps1":  [r'"({key})"',      r"'({key})'"],
    ".cbl":  [r'"({key})"'],
    ".cob":  [r'"({key})"'],
}

# Last-resort pattern for languages not listed above
_FALLBACK_ATTR: list[str] = [r'["\']({key})["\']']


def _lang_patterns(file_path: str, pattern_map: dict[str, list[str]]) -> list[str]:
    ext = Path(file_path).suffix.lower()
    return pattern_map.get(ext, [])


def span_present(source: str, span_name: str, file_path: str) -> bool:
    escaped = re.escape(span_name)
    for tmpl in _lang_patterns(file_path, SPAN_PATTERNS):
        if re.search(tmpl.format(name=escaped), source, re.IGNORECASE):
            return True
    return False


def attr_present(source: str, attr_key: str, file_path: str) -> bool:
    escaped = re.escape(attr_key)
    patterns = _lang_patterns(file_path, ATTR_PATTERNS) or _FALLBACK_ATTR
    for tmpl in patterns:
        if re.search(tmpl.format(key=escaped), source, re.IGNORECASE):
            return True
    return False


# ── Violation data model ──────────────────────────────────────────────────────

class Violation:
    __slots__ = ("contract_id", "contract_name", "kind", "detail", "file")

    # kind values:
    #   missing_attribute   — required attribute not found in source
    #   forbidden_attribute — PII / disallowed attribute present in source
    #   span_not_found      — span name string absent from all source files
    #   file_not_found      — source_files entry does not exist on disk
    #   config_error        — malformed contract (no source_files, etc.)

    def __init__(self, contract_id: str, contract_name: str,
                 kind: str, detail: str, file: str = "") -> None:
        self.contract_id   = contract_id
        self.contract_name = contract_name
        self.kind          = kind
        self.detail        = detail
        self.file          = file

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}

    def __str__(self) -> str:
        loc = f" [{self.file}]" if self.file else ""
        return f"    [{self.kind}]{loc} {self.detail}"


# ── Core validation ───────────────────────────────────────────────────────────

def _attr_key(attr) -> str:
    return attr["key"] if isinstance(attr, dict) else attr


def validate_contract(contract: dict, root: str = ".") -> list[Violation]:
    cid   = contract.get("id") or contract.get("span_name", "?")
    cname = contract.get("description") or contract.get("name", cid)
    span  = contract.get("span_name", "")
    # auto_instrumented=true means the framework creates the span, not user code.
    # Skip the span-name presence check for these (the string won't appear in source).
    auto_inst = contract.get("auto_instrumented", False)

    required  = [_attr_key(a) for a in contract.get("required_attributes",  [])]
    forbidden = [_attr_key(a) for a in contract.get("forbidden_attributes", [])]
    sources   = contract.get("source_files", [])

    violations: list[Violation] = []

    if not sources:
        return [Violation(cid, cname, "config_error", "No source_files defined in contract")]

    found_span            = auto_inst  # skip check when auto-instrumented
    found_attrs: set[str] = set()
    found_forbidden: set[str] = set()

    for sf in sources:
        rel = sf["path"] if isinstance(sf, dict) else sf
        fpath = os.path.join(root, rel)

        if not os.path.exists(fpath):
            violations.append(Violation(cid, cname, "file_not_found",
                                        f"Source file not found: {fpath}", fpath))
            continue

        src = Path(fpath).read_text(encoding="utf-8", errors="replace")

        if not found_span and span:
            if span_present(src, span, fpath):
                found_span = True

        for key in required:
            if attr_present(src, key, fpath):
                found_attrs.add(key)

        for key in forbidden:
            if attr_present(src, key, fpath):
                found_forbidden.add(key)

    if span and not found_span:
        violations.append(Violation(cid, cname, "span_not_found",
                                    f'Span "{span}" not found in any source file'))

    for key in required:
        if key not in found_attrs:
            violations.append(Violation(cid, cname, "missing_attribute",
                                        f'Required attribute "{key}" not set on span "{span}"'))

    for key in found_forbidden:
        violations.append(Violation(cid, cname, "forbidden_attribute",
                                    f'Forbidden attribute "{key}" found — possible PII exposure'))

    return violations


def validate_all(contracts: dict, root: str = ".",
                 filter_id: Optional[str] = None) -> list[Violation]:
    all_v: list[Violation] = []
    for c in contracts.get("contracts", []):
        cid = c.get("id") or c.get("span_name", "?")
        if filter_id and cid != filter_id:
            continue
        all_v.extend(validate_contract(c, root=root))
    return all_v


# ── Report printer ────────────────────────────────────────────────────────────

def print_report(contracts: dict, violations: list[Violation]) -> None:
    all_contracts = contracts.get("contracts", [])
    service = contracts.get("service", "unknown")

    vmap: dict[str, list[Violation]] = {}
    for v in violations:
        vmap.setdefault(v.contract_id, []).append(v)

    pass_count = fail_count = 0
    lines: list[str] = []

    for c in all_contracts:
        cid   = c.get("id") or c.get("span_name", "?")
        cname = c.get("description") or c.get("name", cid)
        span  = c.get("span_name", "-")
        req   = [_attr_key(a) for a in c.get("required_attributes", [])]
        cviol = vmap.get(cid, [])
        n_missing = sum(1 for v in cviol if v.kind == "missing_attribute")

        if cviol:
            fail_count += 1
            status = "FAIL"
        else:
            pass_count += 1
            status = "PASS"

        lines.append(f"\n  [{status}] {cname}")
        lines.append(f"         span: {span}")
        lines.append(f"   attributes: {len(req) - n_missing}/{len(req)} required")
        for v in cviol:
            lines.append(f"         ⚠  {v.kind}: {v.detail}")

    total = pass_count + fail_count
    print(f"\n{'='*64}")
    print(f"Telemetry Contract Report — {service}")
    print(f"{'='*64}")
    print("".join(lines))
    print(f"\n{'='*64}")
    print(f"Result: {pass_count}/{total} contracts fully satisfied")
    if fail_count == 0:
        print("All contracts satisfied. ✓")
    else:
        print(f"{fail_count} contract(s) violated — see details above")
    print()


# ── Drift detection ───────────────────────────────────────────────────────────

def _changed_files(base_ref: Optional[str]) -> list[str]:
    """
    Returns files changed since base_ref (CI mode) or files staged for commit
    (pre-commit hook mode when base_ref is None).
    """
    if base_ref:
        cmd = ["git", "diff", "--name-only", base_ref, "HEAD"]
    else:
        cmd = ["git", "diff", "--cached", "--name-only"]

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return []
    return [f.strip() for f in r.stdout.splitlines() if f.strip()]


def check_drift(contracts: dict, root: str = ".",
                base_ref: Optional[str] = None) -> tuple[list[Violation], list[str]]:
    changed = _changed_files(base_ref)
    if not changed:
        return [], []

    all_violations: list[Violation] = []
    affected_labels: list[str] = []

    def norm(p: str) -> str:
        return os.path.normpath(p)

    for c in contracts.get("contracts", []):
        cid = c.get("id") or c.get("span_name", "?")
        src_paths = [
            (sf["path"] if isinstance(sf, dict) else sf)
            for sf in c.get("source_files", [])
        ]
        # A contract is "touched" when any of its source files appear in the diff
        touched = [
            chf for chf in changed
            if any(
                norm(chf) == norm(s) or norm(chf).endswith(os.sep + norm(s))
                for s in src_paths
            )
        ]
        if not touched:
            continue

        affected_labels.append(f"{cid} (changed: {', '.join(touched)})")

        # Re-validate the contract against current source — any failure is drift
        viol = validate_contract(c, root=root)
        for v in viol:
            v.detail = f"[drift after change to {', '.join(touched)}] {v.detail}"
        all_violations.extend(viol)

    return all_violations, affected_labels


# ── CLI commands ──────────────────────────────────────────────────────────────

def cmd_validate(args: argparse.Namespace) -> None:
    contracts = load_yaml(args.contracts)
    violations = validate_all(contracts, root=args.root,
                              filter_id=getattr(args, "id", None))

    if args.json:
        print(json.dumps([v.as_dict() for v in violations], indent=2))
    else:
        print_report(contracts, violations)
        if violations:
            print(f"{len(violations)} violation(s) found.", file=sys.stderr)

    sys.exit(1 if violations else 0)


def cmd_drift(args: argparse.Namespace) -> None:
    contracts = load_yaml(args.contracts)
    violations, affected = check_drift(contracts, root=args.root,
                                       base_ref=getattr(args, "base", None))

    if not affected:
        print("No contracted source files changed — no drift check needed. ✓")
        sys.exit(0)

    print(f"Contracted files changed: {'; '.join(affected)}")

    if args.json:
        print(json.dumps([v.as_dict() for v in violations], indent=2))
    else:
        if violations:
            print("\nDrift violations:")
            for v in violations:
                print(str(v))
            print()
        else:
            print("Contracts still satisfied after changes. ✓")

    sys.exit(1 if violations else 0)


def cmd_report(args: argparse.Namespace) -> None:
    contracts = load_yaml(args.contracts)
    violations = validate_all(contracts, root=args.root)
    print_report(contracts, violations)
    sys.exit(1 if violations else 0)


# ── Entry point ───────────────────────────────────────────────────────────────

def _add_common_args(p: argparse.ArgumentParser) -> None:
    """Add --contracts, --root, and --json to a subparser."""
    p.add_argument(
        "--contracts", default=".otel/contracts.yaml",
        help="Path to contracts file (default: .otel/contracts.yaml)",
    )
    p.add_argument(
        "--root", default=".",
        help="Repo root for resolving source_file paths (default: .)",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON output")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="otel-contracts",
        description="Telemetry coverage-as-code for OpenTelemetry spans",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit codes: 0 = pass, 1 = violations found, 2 = configuration error\n\n"
            "Examples:\n"
            "  python otel-contracts.py validate\n"
            "  python otel-contracts.py validate --contracts .otel/contracts.yaml\n"
            "  python otel-contracts.py drift --base origin/main\n"
            "  python otel-contracts.py report\n"
            "  python otel-contracts.py validate --id checkout --json"
        ),
    )

    sub = parser.add_subparsers(dest="command", required=True)

    vp = sub.add_parser("validate", help="Check all contracts against current source code")
    vp.add_argument("--id", help="Validate only this contract id")
    _add_common_args(vp)
    vp.set_defaults(func=cmd_validate)

    dp = sub.add_parser("drift", help="Check for attribute drift in recently changed files")
    dp.add_argument(
        "--base",
        help="Git ref to diff against (default: staged files for pre-commit hook mode)",
    )
    _add_common_args(dp)
    dp.set_defaults(func=cmd_drift)

    rp = sub.add_parser("report", help="Print a full coverage summary table")
    _add_common_args(rp)
    rp.set_defaults(func=cmd_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
