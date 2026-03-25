       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL-PROCESSOR.
      *
      * Payroll Batch Processor — COBOL
      * No observability. Run `Observe this project.` to add sidecar OTel.
      *
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-EMP-ID       PIC 9(6).
       01 WS-GROSS-PAY    PIC 9(8)V99.
       01 WS-NET-PAY      PIC 9(8)V99.
       01 WS-DEPT-CODE    PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM PROCESS-PAYROLL
           STOP RUN.
       PROCESS-PAYROLL.
           MOVE 100001 TO WS-EMP-ID
           MOVE 5000.00 TO WS-GROSS-PAY
           MOVE "ENGR" TO WS-DEPT-CODE
           COMPUTE WS-NET-PAY = WS-GROSS-PAY * 0.72
           DISPLAY "Payroll processed: EMP=" WS-EMP-ID " NET=" WS-NET-PAY.
