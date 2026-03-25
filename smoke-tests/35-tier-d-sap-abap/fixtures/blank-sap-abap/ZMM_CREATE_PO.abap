*&---------------------------------------------------------------------*
*& Report  ZMM_CREATE_PO
*& Description: Purchase Order Creation and Material Availability Check
*&              Runs via transaction ME21N / SE38 batch
*&
*& Business context: Creates purchase orders for replenishment of
*& warehouse stock.  For each PO line it calls BAPI_PO_CREATE1 to
*& persist the PO in SAP MM, then BAPI_MATERIAL_AVAILABILITY to check
*& whether stock can satisfy the requested quantity.
*&---------------------------------------------------------------------*
REPORT zmm_create_po.

*---- Types ------------------------------------------------------------*
TYPES:
  BEGIN OF ty_po_request,
    vendor       TYPE lfa1-lifnr,
    material     TYPE mara-matnr,
    plant        TYPE t001w-werks,
    storage_loc  TYPE lgort-lgort,
    quantity     TYPE ekpo-menge,
    unit_price   TYPE ekpo-netpr,
    currency     TYPE waers,
    doc_type     TYPE ekko-bsart,
  END OF ty_po_request.

*---- Data declarations ------------------------------------------------*
DATA:
  lt_po_requests   TYPE STANDARD TABLE OF ty_po_request,
  ls_po_request    TYPE ty_po_request,
  ls_poheader      TYPE bapimepoheader,
  ls_poheaderx     TYPE bapimepoheaderx,
  lt_poitem        TYPE STANDARD TABLE OF bapimepoitem,
  ls_poitem        TYPE bapimepoitem,
  lt_poitemx       TYPE STANDARD TABLE OF bapimepoitemx,
  ls_poitemx       TYPE bapimepoitemx,
  lt_return        TYPE STANDARD TABLE OF bapiret2,
  ls_return        TYPE bapiret2,
  lv_po_number     TYPE ebeln,
  lv_total_value   TYPE ekpo-netwr,
  lv_available     TYPE boolean,
  lv_avail_qty     TYPE ekpo-menge,
  lv_records_ok    TYPE i VALUE 0,
  lv_records_err   TYPE i VALUE 0.

*---- Build list of PO requests ----------------------------------------*
FORM build_po_requests.
  CLEAR lt_po_requests.

  ls_po_request-vendor      = 'V-10023'.
  ls_po_request-material    = 'MAT-5001'.
  ls_po_request-plant       = '1000'.
  ls_po_request-storage_loc = '0001'.
  ls_po_request-quantity    = 500.
  ls_po_request-unit_price  = '12.50'.
  ls_po_request-currency    = 'EUR'.
  ls_po_request-doc_type    = 'NB'.
  APPEND ls_po_request TO lt_po_requests.

  ls_po_request-vendor      = 'V-10087'.
  ls_po_request-material    = 'MAT-3214'.
  ls_po_request-plant       = '1000'.
  ls_po_request-storage_loc = '0002'.
  ls_po_request-quantity    = 200.
  ls_po_request-unit_price  = '89.99'.
  ls_po_request-currency    = 'EUR'.
  ls_po_request-doc_type    = 'NB'.
  APPEND ls_po_request TO lt_po_requests.

  ls_po_request-vendor      = 'V-10055'.
  ls_po_request-material    = 'MAT-9981'.
  ls_po_request-plant       = '2000'.
  ls_po_request-storage_loc = '0001'.
  ls_po_request-quantity    = 1000.
  ls_po_request-unit_price  = '3.75'.
  ls_po_request-currency    = 'EUR'.
  ls_po_request-doc_type    = 'NB'.
  APPEND ls_po_request TO lt_po_requests.
ENDFORM.

*---- Create a single Purchase Order via BAPI --------------------------*
FORM create_purchase_order
    USING    ps_request   TYPE ty_po_request
    CHANGING pv_po_number TYPE ebeln
             pv_total_val TYPE ekpo-netwr.

  CLEAR: ls_poheader, ls_poheaderx,
         lt_poitem, lt_poitemx, lt_return.

  " PO header
  ls_poheader-comp_code  = '1000'.
  ls_poheader-doc_type   = ps_request-doc_type.
  ls_poheader-vendor     = ps_request-vendor.
  ls_poheader-purch_org  = '1000'.
  ls_poheader-pur_group  = '001'.
  ls_poheader-currency   = ps_request-currency.

  ls_poheaderx-comp_code  = 'X'.
  ls_poheaderx-doc_type   = 'X'.
  ls_poheaderx-vendor     = 'X'.
  ls_poheaderx-purch_org  = 'X'.
  ls_poheaderx-pur_group  = 'X'.
  ls_poheaderx-currency   = 'X'.

  " PO item
  ls_poitem-po_item     = '00010'.
  ls_poitem-material    = ps_request-material.
  ls_poitem-plant       = ps_request-plant.
  ls_poitem-stge_loc    = ps_request-storage_loc.
  ls_poitem-quantity    = ps_request-quantity.
  ls_poitem-net_price   = ps_request-unit_price.
  APPEND ls_poitem TO lt_poitem.

  ls_poitemx-po_item    = '00010'.
  ls_poitemx-material   = 'X'.
  ls_poitemx-plant      = 'X'.
  ls_poitemx-stge_loc   = 'X'.
  ls_poitemx-quantity   = 'X'.
  ls_poitemx-net_price  = 'X'.
  APPEND ls_poitemx TO lt_poitemx.

  CALL FUNCTION 'BAPI_PO_CREATE1'
    EXPORTING
      poheader        = ls_poheader
      poheaderx       = ls_poheaderx
    IMPORTING
      exppurchaseorder = pv_po_number
    TABLES
      poitem          = lt_poitem
      poitemx         = lt_poitemx
      return          = lt_return.

  CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'
    EXPORTING
      wait = 'X'.

  " Check for errors
  LOOP AT lt_return INTO ls_return WHERE type = 'E' OR type = 'A'.
    MESSAGE ls_return-message TYPE 'E'.
  ENDLOOP.

  pv_total_val = ps_request-quantity * ps_request-unit_price.

  WRITE: / 'PO created:',
           pv_po_number,
           'vendor:', ps_request-vendor,
           'material:', ps_request-material,
           'value EUR:', pv_total_val.
ENDFORM.

*---- Check material availability via BAPI -----------------------------*
FORM check_material_availability
    USING    ps_request   TYPE ty_po_request
    CHANGING pv_available TYPE boolean
             pv_avail_qty TYPE ekpo-menge.

  DATA: ls_mbgmcr TYPE bapimbgmcr,
        lt_avail  TYPE STANDARD TABLE OF bapimrpavailability,
        ls_avail  TYPE bapimrpavailability,
        lt_ret    TYPE STANDARD TABLE OF bapiret2.

  CALL FUNCTION 'BAPI_MATERIAL_AVAILABILITY'
    EXPORTING
      plant          = ps_request-plant
      material       = ps_request-material
      unit           = 'EA'
    IMPORTING
      av_qty_plt     = pv_avail_qty
    TABLES
      wmdvsx         = lt_avail
      return         = lt_ret.

  IF pv_avail_qty >= ps_request-quantity.
    pv_available = abap_true.
  ELSE.
    pv_available = abap_false.
    WRITE: / 'BACKORDER: material', ps_request-material,
             'available:', pv_avail_qty,
             'requested:', ps_request-quantity.
  ENDIF.
ENDFORM.

*---- Main processing --------------------------------------------------*
START-OF-SELECTION.

  PERFORM build_po_requests.

  WRITE: / 'ZMM_CREATE_PO starting.'.
  WRITE: / 'PO requests to process:', lines( lt_po_requests ).

  LOOP AT lt_po_requests INTO ls_po_request.
    CLEAR: lv_po_number, lv_total_value, lv_available, lv_avail_qty.

    " Create the purchase order
    PERFORM create_purchase_order
      USING    ls_po_request
      CHANGING lv_po_number
               lv_total_value.

    " Check material availability
    PERFORM check_material_availability
      USING    ls_po_request
      CHANGING lv_available
               lv_avail_qty.

    ADD 1 TO lv_records_ok.
  ENDLOOP.

  WRITE: / 'ZMM_CREATE_PO complete.'.
  WRITE: / '  POs created successfully:', lv_records_ok.
  WRITE: / '  POs with errors:',          lv_records_err.
