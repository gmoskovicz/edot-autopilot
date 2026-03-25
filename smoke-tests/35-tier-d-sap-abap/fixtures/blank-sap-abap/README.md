# ZMM_CREATE_PO — SAP ABAP Purchase Order Creation

A custom SAP ABAP report (program type `1`) that creates purchase
orders in SAP MM and checks material availability.  Runs via
transaction `ME21N` or in background via `SE38` / job scheduler.

## Business flows

- **ZMM_CREATE_PO (main report)** — Iterates over a list of PO
  requests (vendor, material, plant, quantity, unit price) and
  orchestrates BAPI calls for each one.
- **BAPI_PO_CREATE1** — SAP standard BAPI that creates a purchase
  order document in MM.  Returns the PO number (e.g. `4500123456`).
  Followed by `BAPI_TRANSACTION_COMMIT` to persist the document.
- **BAPI_MATERIAL_AVAILABILITY** — Checks whether the requested
  quantity is available in the given plant.  Returns available
  quantity; if below requested, the report logs a backorder warning.

## Business context

This program is used by the Procurement team to bulk-create
replenishment POs when warehouse stock falls below reorder levels.
A typical run creates 3–50 POs across plants `1000` and `2000`.
PO values range from EUR 375 to EUR 18 000.

## Environment

- SAP ERP 6.0 EHP 8, ABAP 7.52
- Transaction: ME21N (interactive), SE38/SM36 (background)
- Purchasing org: `1000`, company code: `1000`
- Plants: `1000` (Hamburg), `2000` (Munich)

## No observability yet

This program has no OpenTelemetry instrumentation.  There are no
HTTP calls to an OTel sidecar, no span start/end calls, and no
metrics emission.  It produces only ABAP `WRITE` statements and
a standard return code.
