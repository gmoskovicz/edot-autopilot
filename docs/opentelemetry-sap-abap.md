# OpenTelemetry for SAP ABAP — Complete Guide

> How to get distributed traces out of SAP ABAP programs — custom Z-programs, BAPIs, RFCs, and batch jobs — and into Elastic APM, without modifying the SAP basis or installing any agent on the application server.

SAP ABAP has no official OpenTelemetry SDK. Every mainstream APM vendor stops here. This guide shows the only practical approach: a telemetry sidecar that ABAP calls via HTTP.

---

## The challenge with SAP ABAP and OpenTelemetry

SAP ABAP runs inside the ABAP Application Server (AS ABAP), a proprietary runtime environment that cannot load external agents or shared libraries. The OTel Java agent cannot be injected. There is no ABAP port of the OTel SDK.

What ABAP can do: make HTTP calls. The `CL_HTTP_CLIENT` class and the `CALL METHOD ... http_client->send` pattern have been available since SAP Basis 6.40. On older systems, external shell commands are possible via `CALL 'SYSTEM'`.

This is enough.

---

## Architecture

```
[ABAP Program / Z-Report / BAPI]
        |
        | HTTP POST (JSON)
        v
[otel-sidecar :9411]          ← Python, runs on the same host or a sidecar container
        |
        | OTLP HTTP
        v
[Elastic APM / Elastic Cloud]
```

The ABAP program calls the sidecar. The sidecar translates the call into an OTLP span and forwards it to Elastic. The ABAP runtime never handles OTel directly.

---

## The ABAP caller utility

Add this utility class or include to your ABAP system. It wraps the HTTP call in a `CATCH` block so telemetry failures never impact the business process.

```abap
*&---------------------------------------------------------------------*
*& Include / Class: ZCL_OTEL_SIDECAR
*& Purpose: Fire-and-forget OpenTelemetry event via HTTP sidecar
*&---------------------------------------------------------------------*

CLASS zcl_otel_sidecar DEFINITION PUBLIC FINAL CREATE PUBLIC.
  PUBLIC SECTION.
    CLASS-METHODS emit_event
      IMPORTING
        iv_name       TYPE string
        iv_attributes TYPE string DEFAULT '{}'.  " JSON object string

    CLASS-METHODS start_span
      IMPORTING
        iv_name       TYPE string
        iv_attributes TYPE string DEFAULT '{}'
      RETURNING
        VALUE(rv_span_id) TYPE string.

    CLASS-METHODS end_span
      IMPORTING
        iv_span_id    TYPE string
        iv_attributes TYPE string DEFAULT '{}'
        iv_error      TYPE string OPTIONAL.

  PRIVATE SECTION.
    CONSTANTS: gc_sidecar_url TYPE string VALUE 'http://127.0.0.1:9411'.
    CLASS-METHODS post_json
      IMPORTING
        iv_body TYPE string.
ENDCLASS.

CLASS zcl_otel_sidecar IMPLEMENTATION.

  METHOD emit_event.
    DATA(lv_body) = |{"action":"event","name":"{ iv_name }","attributes":{ iv_attributes }}|.
    post_json( lv_body ).
  ENDMETHOD.

  METHOD start_span.
    " For simple fire-and-forget spans use emit_event instead.
    " start_span / end_span is for long-running operations (batch jobs, RFCs).
    DATA(lv_body) = |{"action":"start_span","name":"{ iv_name }","attributes":{ iv_attributes }}|.
    post_json( lv_body ).
    " Return a UUID as span_id; in a real impl parse the sidecar response
    rv_span_id = sy-uzeit && sy-datum.
  ENDMETHOD.

  METHOD end_span.
    DATA lv_error_part TYPE string.
    IF iv_error IS NOT INITIAL.
      lv_error_part = |,"error":"{ iv_error }"|.
    ENDIF.
    DATA(lv_body) = |{"action":"end_span","span_id":"{ iv_span_id }","attributes":{ iv_attributes }{ lv_error_part }}|.
    post_json( lv_body ).
  ENDMETHOD.

  METHOD post_json.
    " Fire-and-forget: ignore errors so telemetry never blocks business logic
    TRY.
        DATA(lo_client) = cl_http_client=>create_by_url( gc_sidecar_url ).
        lo_client->request->set_method( 'POST' ).
        lo_client->request->set_header_field(
          name  = 'Content-Type'
          value = 'application/json' ).
        lo_client->request->set_cdata( iv_body ).
        lo_client->send( ).
        lo_client->close( ).
      CATCH cx_root.
        " Never let telemetry failures surface to the user
    ENDTRY.
  ENDMETHOD.

ENDCLASS.
```

---

## Usage in a Z-program or batch job

Place the call immediately after the business operation — not at the top of the report.

```abap
*&---------------------------------------------------------------------*
*& Report: ZORDER_BATCH_PROCESSOR
*& Example: OpenTelemetry instrumentation for a batch order processor
*&---------------------------------------------------------------------*

REPORT zorder_batch_processor.

" ... existing program logic ...

" After processing each order, emit a telemetry event:
DATA(lv_attrs) = |{"order.id":"{ lv_order_id }",|
              && |"order.value_usd":{ lv_total_amount },|
              && |"customer.tier":"{ lv_customer_tier }",|
              && |"batch.run_id":"{ lv_run_id }",|
              && |"order.item_count":{ lv_item_count }}|.

zcl_otel_sidecar=>emit_event(
  iv_name       = 'order.processed'
  iv_attributes = lv_attrs ).

" For long-running operations (RFC calls, BAPI calls), use start/end:
DATA(lv_span_id) = zcl_otel_sidecar=>start_span(
  iv_name       = 'bapi.sales_order.create'
  iv_attributes = '{"bapi.name":"BAPI_SALESORDER_CREATEFROMDAT2"}' ).

" ... BAPI call ...
CALL FUNCTION 'BAPI_SALESORDER_CREATEFROMDAT2'
  EXPORTING  order_header_in = ls_header
  IMPORTING  salesdocument   = lv_doc_number
  TABLES     return          = lt_return.

zcl_otel_sidecar=>end_span(
  iv_span_id    = lv_span_id
  iv_attributes = |{"sales.document":"{ lv_doc_number }","order.currency":"{ lv_currency }"}| ).
```

---

## For older ABAP systems without CL_HTTP_CLIENT

On SAP systems older than Basis 6.40, use `CALL 'SYSTEM'` to invoke curl:

```abap
DATA: lv_cmd TYPE string,
      lv_rc  TYPE i.

CONCATENATE
  'curl -sf -X POST http://127.0.0.1:9411'
  ' -H "Content-Type: application/json"'
  ' -d "{\"action\":\"event\",\"name\":\"order.processed\","'
  '\"attributes\":{\"order.id\":\"' lv_order_id '\"}}"'
  ' >/dev/null 2>&1 || true'
  INTO lv_cmd.

CALL 'SYSTEM'
  ID 'COMMAND' FIELD lv_cmd
  ID 'TAB'     FIELD lv_rc.
```

---

## Running the sidecar on SAP infrastructure

### Option A: Same host as the SAP Application Server

```bash
export OTEL_SERVICE_NAME=sap-erp-production
export ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io
export ELASTIC_API_KEY=<your-api-key>
export SIDECAR_PORT=9411

python3 otel-sidecar.py &
```

### Option B: Docker container in the same network

```yaml
services:
  otel-sidecar:
    image: gmoskovicz/edot-autopilot-sidecar:latest
    network_mode: host          # ABAP calls 127.0.0.1:9411
    environment:
      OTEL_SERVICE_NAME:    sap-erp-production
      ELASTIC_OTLP_ENDPOINT: ${ELASTIC_OTLP_ENDPOINT}
      ELASTIC_API_KEY:       ${ELASTIC_API_KEY}
    restart: unless-stopped
```

---

## What to instrument in SAP ABAP

Focus on operations with business impact — not every program:

| SAP object | Span name pattern | Key attributes |
|---|---|---|
| Sales order creation (BAPI) | `bapi.sales_order.create` | `sales.document`, `order.value`, `sold_to_party` |
| Delivery processing | `bapi.delivery.process` | `delivery.number`, `warehouse.number` |
| FI posting | `fi.document.post` | `fi.document`, `posting.amount`, `cost.center` |
| Batch job step | `batch.job.step` | `job.name`, `job.step`, `rows.processed` |
| RFC call | `rfc.call` | `rfc.function`, `rfc.destination`, `rfc.duration_ms` |
| IDoc processing | `idoc.process` | `idoc.number`, `idoc.type`, `idoc.status` |

**Key attributes for SAP observability:**
- `sap.client` — the SAP client number (e.g., `100`)
- `sap.system_id` — the system ID (e.g., `PRD`, `QAS`)
- `sap.transaction` — the SAP transaction code
- `sap.program` — the ABAP program name
- `sap.user` — the SAP user (not `sy-uname` directly — hash for PII compliance)

---

## Verifying in Elastic APM

After the sidecar is running and your ABAP program executes:

1. Open Kibana → Observability → APM → Services
2. Look for the service named by `OTEL_SERVICE_NAME` (e.g., `sap-erp-production`)
3. Navigate to Transactions → find your span names (e.g., `order.processed`)
4. Confirm business attributes are present: `order.value_usd`, `customer.tier`, etc.

---

## Related guides

- [OpenTelemetry for IBM RPG (AS/400)](opentelemetry-ibm-rpg.md) — the same sidecar pattern for IBM i
- [OpenTelemetry for COBOL](opentelemetry-cobol.md) — mainframe batch job instrumentation
- [Telemetry Sidecar Pattern](telemetry-sidecar-pattern.md) — full sidecar documentation
- [Business Span Enrichment](business-span-enrichment.md) — what attributes to capture

---

*Part of [EDOT Autopilot](https://github.com/gmoskovicz/edot-autopilot) — OpenTelemetry autopilot for any codebase.*
