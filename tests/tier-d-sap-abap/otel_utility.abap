"! OTel Sidecar Utility Class for SAP ABAP
"! Emits observability spans to the otel-sidecar via HTTP.
"!
"! Usage:
"!   zcl_otel_sidecar=>emit_event(
"!     iv_name       = 'sap.order.processed'
"!     iv_attributes = '{"order.id":"0100000001","order.value_usd":4200}'
"!   ).
CLASS zcl_otel_sidecar DEFINITION
  PUBLIC
  FINAL
  CREATE PUBLIC.

  PUBLIC SECTION.
    CLASS-METHODS:
      "! Fire-and-forget event span
      emit_event
        IMPORTING
          iv_name       TYPE string
          iv_attributes TYPE string DEFAULT '{}',

      "! Start a long-running span, returns span_id
      start_span
        IMPORTING
          iv_name       TYPE string
          iv_attributes TYPE string DEFAULT '{}'
        RETURNING
          VALUE(rv_span_id) TYPE string,

      "! End a span
      end_span
        IMPORTING
          iv_span_id    TYPE string
          iv_attributes TYPE string DEFAULT '{}'
          iv_error      TYPE string OPTIONAL.

  PRIVATE SECTION.
    CONSTANTS:
      c_sidecar_url TYPE string VALUE 'http://127.0.0.1:9411'.

    CLASS-METHODS:
      post_to_sidecar
        IMPORTING
          iv_body           TYPE string
        RETURNING
          VALUE(rv_response) TYPE string.
ENDCLASS.

CLASS zcl_otel_sidecar IMPLEMENTATION.

  METHOD emit_event.
    DATA(lv_body) = |{"action":"event","name":"| && iv_name &&
                   |","attributes":| && iv_attributes && |}|.
    post_to_sidecar( lv_body ).
  ENDMETHOD.

  METHOD start_span.
    DATA(lv_body) = |{"action":"start_span","name":"| && iv_name &&
                   |","attributes":| && iv_attributes && |}|.
    DATA(lv_resp) = post_to_sidecar( lv_body ).
    " Parse span_id from JSON response (simplified)
    FIND REGEX |"span_id":"([^"]+)"| IN lv_resp
      SUBMATCHES rv_span_id.
  ENDMETHOD.

  METHOD end_span.
    DATA lv_body TYPE string.
    IF iv_error IS SUPPLIED AND iv_error IS NOT INITIAL.
      lv_body = |{"action":"end_span","span_id":"| && iv_span_id &&
                |","attributes":| && iv_attributes &&
                |,"error":"| && iv_error && |"}|.
    ELSE.
      lv_body = |{"action":"end_span","span_id":"| && iv_span_id &&
                |","attributes":| && iv_attributes && |}|.
    ENDIF.
    post_to_sidecar( lv_body ).
  ENDMETHOD.

  METHOD post_to_sidecar.
    DATA: lo_client  TYPE REF TO if_http_client,
          lo_request TYPE REF TO if_http_request.

    cl_http_client=>create_by_url(
      EXPORTING url = c_sidecar_url
      IMPORTING client = lo_client
      EXCEPTIONS OTHERS = 1
    ).

    " If HTTP client creation fails, return silently — never block business logic
    IF sy-subrc <> 0 OR lo_client IS INITIAL.
      RETURN.
    ENDIF.

    TRY.
      lo_request = lo_client->request.
      lo_request->set_method( if_http_request=>co_request_method_post ).
      lo_request->set_header_field(
        name  = 'Content-Type'
        value = 'application/json'
      ).
      lo_request->set_cdata( iv_body ).

      lo_client->send(
        EXCEPTIONS
          http_communication_failure = 1
          OTHERS                     = 2
      ).

      IF sy-subrc = 0.
        lo_client->receive( EXCEPTIONS OTHERS = 1 ).
        lo_client->response->get_cdata( RECEIVING data = rv_response ).
      ENDIF.

      lo_client->close( ).
    CATCH cx_root.
      " Never let telemetry failures propagate
      TRY. lo_client->close( ). CATCH cx_root. ENDTRY.
    ENDTRY.
  ENDMETHOD.

ENDCLASS.
