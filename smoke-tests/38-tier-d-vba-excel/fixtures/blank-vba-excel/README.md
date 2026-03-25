# blank-vba-excel — Group P&L Consolidation Macro (VBA / Excel)

## What this macro does

`macro.vba` is a VBA module in `GroupConsolidation_2026Q1.xlsm`. It implements
the monthly Group P&L financial consolidation:

1. **LoadFXRates** — reads FX rates (EUR/USD, SGD/USD, BRL/USD) from the
   `FX_Rates` worksheet
2. **Workbook.Open** — opens each subsidiary P&L workbook from a UNC path
   (`\\FINANCE-SRV\Consolidation\2026Q1\`)
3. **Range.Read** — reads revenue, COGS, and OPEX values from the `P&L`
   worksheet (column B, rows 4-6)
4. **FX_Conversion** — multiplies each line item by the subsidiary's FX rate
   to convert to USD
5. **Range.Write_Consolidation** — writes the USD-converted values into the
   `Group P&L` worksheet, one column per subsidiary
6. **WriteGroupTotals** — writes SUM formulas for group-level totals and GP
   margin percentage

Subsidiaries: EMEA-GmbH (EUR), APAC-Pte (SGD), LATAM-SA (BRL), NA-Corp (USD).

## Why it has no observability

This is a **Tier D** legacy application. VBA macros running inside Excel have
no OpenTelemetry SDK. The VBA runtime cannot load OTel agents.

There are no HTTP calls, no sidecar references, no trace/span IDs — just
`Debug.Print` and `MsgBox` statements.

The EDOT Autopilot agent must:
1. Copy `otel-sidecar.py` into the project
2. Modify `macro.vba` to add `WinHttp.WinHttpRequest` POST calls targeting
   the sidecar so that each consolidation step emits a span
3. Create `.otel/slos.json` and `.otel/golden-paths.md`
