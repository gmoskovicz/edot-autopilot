# New-HireProvisioning — PowerShell AD Automation

A PowerShell script that automates new-employee onboarding across
on-premises Active Directory and Microsoft 365.  HR IT-Ops runs it
every Monday morning after the weekly new-hire CSV is exported from
Workday.

## Business flows

- **Invoke-NewHireProvisioning** — Top-level function called once per
  new hire.  Orchestrates all three sub-steps below.
- **New-ADUser** — Creates the employee's Active Directory account in
  the correct department OU, sets a temporary password, and enables
  the account.
- **Add-ADGroupMember** — Assigns the employee to department-specific
  security groups (e.g. `eng-all`, `github-org`, `vpn-access`).
  Called once per group — typically 3–5 calls per hire.
- **Enable-Mailbox / Enable-RemoteMailbox** — Provisions the
  Microsoft 365 mailbox with an E3 licence and sets a 100 MB receive
  quota via Exchange Online Management shell.

## Business context

Each provisioning run handles 5–50 new hires.  AD user creation
typically takes 200–400 ms; mailbox provisioning takes 300–600 ms
due to Exchange Online propagation lag.  Failures must page the
IT-Ops on-call because blocked AD accounts delay Day-1 access.

## Environment

- Windows Server 2022, PowerShell 7.4
- Modules: `ActiveDirectory` (RSAT), `ExchangeOnlineManagement` 3.x
- AD Domain: `company.corp`
- M365 tenant: `company.onmicrosoft.com`

## No observability yet

This script has no OpenTelemetry instrumentation.  There are no
HTTP calls to an OTel sidecar, no span start/end calls, and no
metrics emission.  It produces only `Write-Host` log lines and
a PowerShell exit code.
