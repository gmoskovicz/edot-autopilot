# blank-zapier — Lead Nurturing Automation (Zapier No-Code)

## What this Zap does

`lead_nurture_zap.json` is a Zapier workflow definition (Zap ID: ZAP-48291)
that automates a 5-step lead nurturing pipeline triggered by new Salesforce
leads:

1. **Salesforce: Find Lead** — retrieves the full lead record (including custom
   fields) from Salesforce CRM by lead ID from the trigger payload
2. **Clearbit: Enrich Person** — calls the Clearbit Enrichment API with the
   lead's email to obtain company size, funding stage, job seniority, and
   technology stack information
3. **HubSpot: Create/Update Contact** — upserts the enriched lead into HubSpot
   CRM using email as the unique key; sets `hs_lead_status = NEW` and
   `clearbit_seniority` custom property
4. **Slack: Send Channel Message** — posts a formatted notification to the
   `#sales-alerts` Slack channel with lead name, title, company, and a link
   to the HubSpot contact
5. **Mailchimp: Add/Update Subscriber** — adds the lead to the correct
   Mailchimp nurture audience (`f3a9c2b1d0`) with `source` and `new-lead-2026`
   tags for segmentation

The Zap is configured to continue on step failure (with retry), with error
notifications sent to `zapier-errors@company.com`.

## Why it has no observability

This is a **Tier D** no-code automation. Zapier workflows run on Zapier's
proprietary cloud infrastructure — there is no SDK, no agent injection, and
no access to the execution runtime.

There are no HTTP sidecar calls, no trace headers, no span IDs — the workflow
is defined entirely as JSON configuration with no custom code.

The EDOT Autopilot agent must:
1. Copy `otel-sidecar.py` into the project
2. Add a Zapier "Code by Zapier" (JavaScript) step or a Webhooks by Zapier step
   that POSTs span data to the sidecar for each automation step
3. Create `.otel/slos.json` and `.otel/golden-paths.md`
