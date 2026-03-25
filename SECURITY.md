# Security Policy

## Supported Versions

Security fixes are applied to the latest commit on the `main` branch only. No backport releases are maintained.

| Version | Supported |
|---|---|
| `main` (latest) | Yes |
| Any pinned older commit | No |

---

## Scope

This security policy covers the files in this repository:

- `CLAUDE.md` — the observability workflow definition consumed by Claude Code
- `otel-sidecar.py` — the HTTP-to-OTLP bridge process
- Smoke tests under `smoke-tests/`
- Supporting scripts and configuration files in this repo

This policy does **not** cover the Elastic, OpenTelemetry, or NVIDIA projects that this repository references. Report vulnerabilities in those projects to their respective security teams.

---

## Network Exposure

**The otel-sidecar binds exclusively to `127.0.0.1:9411` by default.** It must never be exposed to external networks or bound to `0.0.0.0`.

The sidecar accepts unauthenticated POST requests from any process on the same host. It is designed to run in a trusted local environment (same host or same Docker network namespace as the legacy process it serves). Do not place it behind a public-facing proxy or expose it outside the machine boundary.

If you need to run the sidecar in a shared environment where untrusted processes may be present on the same host, treat the sidecar port as an attack surface and apply appropriate host-level firewall rules.

---

## Reporting a Vulnerability

If you discover a security issue in this project, please report it privately rather than opening a public GitHub issue.

**Use GitHub's private vulnerability reporting:**

1. Go to the repository on GitHub: https://github.com/gmoskovicz/edot-autopilot
2. Click **Security** in the top navigation
3. Click **Advisories**
4. Click **Report a vulnerability**

GitHub will keep the report private until a fix is available and a coordinated disclosure date is agreed upon.

Please include:
- A description of the vulnerability and its potential impact
- Steps to reproduce
- Any suggested fix or mitigation you have identified

You can expect an acknowledgment within 5 business days.
