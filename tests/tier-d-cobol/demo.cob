       IDENTIFICATION DIVISION.
       PROGRAM-ID. OTEL-DEMO.
      *----------------------------------------------------------------
      * Tier D — COBOL with OTEL Sidecar
      *
      * COBOL has no OpenTelemetry SDK. But COBOL can call SYSTEM to
      * execute curl. That's all we need.
      *
      * This program simulates an order processing batch — the kind
      * that runs on a mainframe at night and processes millions of
      * dollars in transactions with zero observability.
      *
      * With the sidecar, every critical business event emits a span
      * to Elastic APM — no changes to the COBOL runtime required.
      *
      * Prerequisites:
      *   - otel-sidecar running on localhost:9411
      *   - curl available on the host (AIX, z/OS with Unix Services, Linux)
      *
      * Compile: cobc -x -free demo.cob -o otel-demo
      * Run:     ./otel-demo
      *----------------------------------------------------------------

       ENVIRONMENT DIVISION.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
           01 WS-ORDER-ID        PIC X(20).
           01 WS-AMOUNT          PIC 9(8)V99.
           01 WS-AMOUNT-STR      PIC X(12).
           01 WS-CUSTOMER-TIER   PIC X(20).
           01 WS-CURL-CMD        PIC X(512).
           01 WS-RC              PIC 9(4).
           01 WS-COUNTER         PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "ORDER PROCESSING BATCH STARTED"

      *    Process three sample orders
           MOVE "ORD-001" TO WS-ORDER-ID
           MOVE 4200.00   TO WS-AMOUNT
           MOVE "enterprise" TO WS-CUSTOMER-TIER
           PERFORM PROCESS-ORDER

           MOVE "ORD-002" TO WS-ORDER-ID
           MOVE 29.99     TO WS-AMOUNT
           MOVE "free"    TO WS-CUSTOMER-TIER
           PERFORM PROCESS-ORDER

           MOVE "ORD-003" TO WS-ORDER-ID
           MOVE 1250.00   TO WS-AMOUNT
           MOVE "pro"     TO WS-CUSTOMER-TIER
           PERFORM PROCESS-ORDER

           DISPLAY "BATCH COMPLETE. CHECK KIBANA APM."
           STOP RUN.

       PROCESS-ORDER.
      *    Emit telemetry event to sidecar via curl
      *    Business data: order.id, order.value_usd, customer.tier
           MOVE FUNCTION NUMVAL(WS-AMOUNT) TO WS-AMOUNT
           MOVE WS-AMOUNT TO WS-AMOUNT-STR

           STRING
               'curl -sf -X POST http://127.0.0.1:9411'
               ' -H "Content-Type: application/json"'
               ' -d "{\"action\":\"event\","
               '\"name\":\"order.processed\","
               '\"attributes\":{"
               '\"order.id\":\"' WS-ORDER-ID '\",'
               '\"order.value_usd\":' WS-AMOUNT-STR ','
               '\"customer.tier\":\"' WS-CUSTOMER-TIER '\"'
               '}}" > /dev/null 2>&1 || true'
               DELIMITED SIZE INTO WS-CURL-CMD

           CALL "SYSTEM" USING WS-CURL-CMD
                              RETURNING WS-RC

           ADD 1 TO WS-COUNTER

           DISPLAY "PROCESSED " WS-ORDER-ID
                   " $" WS-AMOUNT-STR
                   " [" WS-CUSTOMER-TIER "]".
