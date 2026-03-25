# blank-delphi — Point-of-Sale Transaction Processing (Delphi / Object Pascal)

## What this unit does

`POSTransaction.pas` is a Delphi 11.3 (Alexandria) unit implementing the core
POS transaction processing workflow:

1. **TBarcodeScanner.LookupSKU** — queries the Firebird 3.0 `inventory` table
   via `TFDQuery` to retrieve SKU code, description, unit price, and tax rate
   for each scanned barcode
2. **TPaymentGateway.Authorize** — sends the payment authorization request to
   the Verifone card reader via RS-232 (ISO 8583 protocol), waits for approval,
   and returns an auth code
3. **TReceiptPrinter.PrintReceipt** — sends ESC/POS commands to the Epson
   TM-T88VII thermal printer via USB
4. **TDatabase.CommitTransaction** — inserts the transaction header and all
   line items into Firebird (`transactions` and `transaction_lines` tables)
   within a `StartTransaction`/`Commit` block

The `TTransactionForm.ProcessSale` method orchestrates the full sale: cart
total calculation, payment authorization, receipt printing, and DB commit.

## Why it has no observability

This is a **Tier D** legacy application. Delphi / Object Pascal applications
compiled against Win32/Win64 VCL have no OpenTelemetry SDK. Delphi components
cannot auto-instrument via OTel Java/Python agents.

There are no HTTP calls, no sidecar references, no trace/span IDs — just
`Writeln` calls and Firebird database operations.

The EDOT Autopilot agent must:
1. Copy `otel-sidecar.py` into the project
2. Modify `POSTransaction.pas` to add `TIdHTTP` (Indy) or `TNetHTTPClient`
   POST calls targeting the sidecar so that each POS step emits a span
3. Create `.otel/slos.json` and `.otel/golden-paths.md`
