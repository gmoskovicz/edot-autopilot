      *================================================================*
      * PROGRAM-ID: PAYRLL01                                          *
      * DESCRIPTION: End-of-month payroll batch processing            *
      *              Reads EMPMASTER VSAM file, calculates gross/net  *
      *              pay, writes disbursement records to OUTFILE.     *
      *                                                               *
      * JCL JOB CLASS: A   REGION: 512M                               *
      * BATCH PERIOD:  Monthly (run on last business day)             *
      *================================================================*
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYRLL01.
       AUTHOR. PAYROLL-TEAM.
       DATE-WRITTEN. 2024-01-15.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EMPMASTR ASSIGN TO EMPMASTR
               ORGANIZATION IS INDEXED
               ACCESS MODE IS SEQUENTIAL
               RECORD KEY IS WS-EMP-ID
               FILE STATUS IS WS-EMP-STATUS.

           SELECT DISBFILE ASSIGN TO DISBFILE
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-DISB-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  EMPMASTR
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  EMP-RECORD.
           05 EMP-ID           PIC X(6).
           05 EMP-NAME         PIC X(30).
           05 EMP-DEPARTMENT   PIC X(12).
           05 EMP-HOURS-WORKED PIC 9(3).
           05 EMP-HOURLY-RATE  PIC 9(5)V99.
           05 EMP-TAX-PCT      PIC 9(2)V99.

       FD  DISBFILE
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  DISB-RECORD.
           05 DISB-EMP-ID      PIC X(6).
           05 DISB-NAME        PIC X(30).
           05 DISB-GROSS-PAY   PIC 9(9)V99.
           05 DISB-NET-PAY     PIC 9(9)V99.
           05 DISB-TAX-AMT     PIC 9(9)V99.
           05 DISB-DEPARTMENT  PIC X(12).

       WORKING-STORAGE SECTION.
       01  WS-EMPLOYEE-TABLE.
           05 WS-EMP-ID        PIC X(6).
           05 WS-EMP-NAME      PIC X(30).
           05 WS-DEPARTMENT    PIC X(12).
           05 WS-HOURS         PIC 9(3).
           05 WS-RATE          PIC 9(5)V99.
           05 WS-TAX-PCT       PIC 9(2)V99.

       01  WS-CALCULATIONS.
           05 WS-GROSS-PAY     PIC 9(9)V99.
           05 WS-TAX-AMOUNT    PIC 9(9)V99.
           05 WS-NET-PAY       PIC 9(9)V99.
           05 WS-TOTAL-GROSS   PIC 9(11)V99 VALUE ZEROS.
           05 WS-TOTAL-NET     PIC 9(11)V99 VALUE ZEROS.
           05 WS-RECORDS-READ  PIC 9(5) VALUE ZEROS.
           05 WS-RECORDS-WRIT  PIC 9(5) VALUE ZEROS.

       01  WS-STATUS.
           05 WS-EMP-STATUS    PIC XX VALUE SPACES.
           05 WS-DISB-STATUS   PIC XX VALUE SPACES.
           05 WS-EOF-FLAG      PIC X VALUE 'N'.
               88 END-OF-FILE  VALUE 'Y'.

       01  WS-BATCH-PERIOD     PIC X(7) VALUE '2026-02'.
       01  WS-JOB-CLASS        PIC X    VALUE 'A'.
       01  WS-REGION-MB        PIC 9(4) VALUE 512.

       01  WS-DISPLAY-GROSS    PIC $$$,$$$,$$9.99.
       01  WS-DISPLAY-NET      PIC $$$,$$$,$$9.99.
       01  WS-DISPLAY-TOTAL    PIC $$$,$$$,$$$,$$9.99.

       PROCEDURE DIVISION.
       MAIN-ROUTINE.
           DISPLAY 'PAYRLL01 STARTING - PERIOD: ' WS-BATCH-PERIOD
           PERFORM OPEN-FILES
           PERFORM READ-EMPMASTER
           PERFORM WRITE-DISBURSEMENTS
           PERFORM CLOSE-FILES
           DISPLAY 'PAYRLL01 COMPLETE'
           DISPLAY '  RECORDS READ:    ' WS-RECORDS-READ
           DISPLAY '  RECORDS WRITTEN: ' WS-RECORDS-WRIT
           MOVE WS-TOTAL-GROSS TO WS-DISPLAY-TOTAL
           DISPLAY '  TOTAL GROSS PAY: ' WS-DISPLAY-TOTAL
           STOP RUN.

       OPEN-FILES.
           OPEN INPUT EMPMASTR
           IF WS-EMP-STATUS NOT = '00'
               DISPLAY 'ERROR OPENING EMPMASTR: ' WS-EMP-STATUS
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF
           OPEN OUTPUT DISBFILE
           IF WS-DISB-STATUS NOT = '00'
               DISPLAY 'ERROR OPENING DISBFILE: ' WS-DISB-STATUS
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF.

       READ-EMPMASTER.
           DISPLAY 'READING EMPMASTER FILE...'
           READ EMPMASTR
               AT END MOVE 'Y' TO WS-EOF-FLAG
           END-READ
           PERFORM UNTIL END-OF-FILE
               ADD 1 TO WS-RECORDS-READ
               MOVE EMP-ID           TO WS-EMP-ID
               MOVE EMP-NAME         TO WS-EMP-NAME
               MOVE EMP-DEPARTMENT   TO WS-DEPARTMENT
               MOVE EMP-HOURS-WORKED TO WS-HOURS
               MOVE EMP-HOURLY-RATE  TO WS-RATE
               MOVE EMP-TAX-PCT      TO WS-TAX-PCT
               PERFORM CALC-PAY
               READ EMPMASTR
                   AT END MOVE 'Y' TO WS-EOF-FLAG
               END-READ
           END-PERFORM
           DISPLAY '  EMPMASTER READ COMPLETE: ' WS-RECORDS-READ
                   ' EMPLOYEES'.

       CALC-PAY.
           MULTIPLY WS-HOURS BY WS-RATE
               GIVING WS-GROSS-PAY
           MULTIPLY WS-GROSS-PAY BY WS-TAX-PCT
               GIVING WS-TAX-AMOUNT
           SUBTRACT WS-TAX-AMOUNT FROM WS-GROSS-PAY
               GIVING WS-NET-PAY
           ADD WS-GROSS-PAY TO WS-TOTAL-GROSS
           ADD WS-NET-PAY   TO WS-TOTAL-NET
           MOVE WS-GROSS-PAY TO WS-DISPLAY-GROSS
           MOVE WS-NET-PAY   TO WS-DISPLAY-NET
           DISPLAY '  EMP: ' WS-EMP-ID ' ' WS-EMP-NAME
                   ' GROSS: ' WS-DISPLAY-GROSS
                   ' NET: '   WS-DISPLAY-NET.

       WRITE-DISBURSEMENTS.
           DISPLAY 'WRITING DISBURSEMENT RECORDS...'
           MOVE WS-EMP-ID    TO DISB-EMP-ID
           MOVE WS-EMP-NAME  TO DISB-NAME
           MOVE WS-GROSS-PAY TO DISB-GROSS-PAY
           MOVE WS-NET-PAY   TO DISB-NET-PAY
           MOVE WS-TAX-AMOUNT TO DISB-TAX-AMT
           MOVE WS-DEPARTMENT TO DISB-DEPARTMENT
           WRITE DISB-RECORD
           ADD 1 TO WS-RECORDS-WRIT
           DISPLAY '  DISBURSEMENTS WRITTEN: ' WS-RECORDS-WRIT
                   ' RECORDS'.

       CLOSE-FILES.
           CLOSE EMPMASTR
           CLOSE DISBFILE.
