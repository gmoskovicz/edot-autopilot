# Tier D — SAP ABAP

SAP ABAP has no OpenTelemetry SDK. SAP's own observability is locked to their ecosystem (SAP Cloud ALM, Focused Run). But ABAP can make HTTP calls via `CL_HTTP_CLIENT`. That's enough.

## The sidecar approach

```
[SAP ABAP program] → CL_HTTP_CLIENT → [otel-sidecar:9411] → OTLP → Elastic APM
```

## ABAP code snippet

```abap
METHOD emit_otel_event.
  DATA: lo_client  TYPE REF TO if_http_client,
        lo_request TYPE REF TO if_http_request,
        lv_body    TYPE string.

  " Build JSON payload
  lv_body = |{ "action":"event","name":"| && iv_name &&
             |","attributes":{ "order.id":"| && iv_order_id &&
             |","order.value_usd":| && iv_amount &&
             |,"customer.tier":"| && iv_tier && |"}}|.

  " Create HTTP client to sidecar
  cl_http_client=>create_by_url(
    EXPORTING
      url    = 'http://127.0.0.1:9411'
    IMPORTING
      client = lo_client
    EXCEPTIONS
      OTHERS = 1
  ).

  IF sy-subrc <> 0.
    RETURN.  " Never let telemetry fail the business process
  ENDIF.

  lo_request = lo_client->request.
  lo_request->set_method( if_http_request=>co_request_method_post ).
  lo_request->set_header_field(
    name  = 'Content-Type'
    value = 'application/json'
  ).
  lo_request->set_cdata( lv_body ).

  lo_client->send( EXCEPTIONS OTHERS = 1 ).
  lo_client->close( ).
ENDMETHOD.
```

## Deployment on SAP NetWeaver / S/4HANA

1. Start the otel-sidecar on the same host as the SAP application server
2. Add the `emit_otel_event` method to a utility class
3. Call it from any business-critical ABAP program:

```abap
" In your order processing FM or method:
me->emit_otel_event(
  iv_name     = 'sap.order.processed'
  iv_order_id = ls_order-vbeln
  iv_amount   = ls_order-netwr
  iv_tier     = 'enterprise'
).
```

## What you get in Elastic APM

- SAP order processing spans with business attributes
- ABAP batch job execution spans
- Pricing/availability check durations
- Cross-system traces: SAP order → downstream microservices

## SAP BTP (cloud)

On SAP BTP, outbound HTTP calls are available via SAP's destination service. The same ABAP snippet works — point the destination to your sidecar URL.

## SAP HANA stored procedures

HANA SQLScript can also make HTTP calls using `SYS.HTTP_POST`. The same JSON payload format works.

```sql
-- HANA SQLScript
CALL SYS.HTTP_POST(
    'http://127.0.0.1:9411',
    '{"action":"event","name":"hana.query.slow","attributes":{"duration_ms":3200,"table":"VBAK"}}',
    'Content-Type: application/json',
    :response_body, :status_code
);
```
