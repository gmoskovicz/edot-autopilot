# blank-classic-asp — Insurance Quote Form (Classic ASP / VBScript)

## What this application does

`default.asp` is a Classic Active Server Pages (ASP/VBScript) page running on
IIS 6.0 / Windows Server 2003. It implements a legacy insurance quote form:

1. **GetRatingFactors** — queries `RatingFactors` table in SQL Server
   (`InsuranceDB`) via `ADODB.Connection.Execute` to look up territory and
   risk modifiers by ZIP code and coverage type
2. **RunUnderwritingRules** — applies age, vehicle, and property factors to
   compute an annual premium estimate
3. **SaveQuote** — inserts the approved quote (quote ID, session, coverage,
   premium) into the `Quotes` table via an `ADODB.Connection.Execute INSERT`
4. **EventLog** — writes a `WScript.Shell.LogEvent` entry for audit purposes
5. **HTML response** — returns the quote ID and annual premium to the browser

Supported coverage types: `auto` and `homeowner`.

## Why it has no observability

This is a **Tier D** legacy application. Classic ASP / VBScript on IIS 6.0 has
no OpenTelemetry SDK. The ASP runtime cannot load managed OTel agents.

There are no HTTP sidecar calls, no trace headers, no span IDs — just
`WScript.Shell.LogEvent` and `Response.Write`.

The EDOT Autopilot agent must:
1. Copy `otel-sidecar.py` into the project
2. Modify `default.asp` to add `MSXML2.ServerXMLHTTP` or `WinHttp.WinHttpRequest`
   POST calls targeting the sidecar so that each major step emits a span
3. Create `.otel/slos.json` and `.otel/golden-paths.md`
