# PAYRLL01 — Payroll Batch Processing

A COBOL batch job that runs at end-of-month on a z/OS mainframe.
It reads the employee master file (EMPMASTER VSAM KSDS), calculates
gross and net pay for each employee, and writes disbursement records
to the OUTFILE sequential dataset.

## Business flows

- **READ-EMPMASTER** — Reads the EMPMASTER VSAM KSDS sequentially.
  Each record holds employee ID, name, department, hours worked,
  hourly rate, and tax percentage.
- **CALC-PAY** — Computes gross pay (`hours × rate`), tax amount
  (`gross × tax_pct`), and net pay (`gross − tax`).  Called once per
  employee record.
- **WRITE-DISBURSEMENTS** — Writes one disbursement record per employee
  to the OUTFILE sequential dataset.  Each record carries employee ID,
  name, gross pay, net pay, tax amount, and department.

## Business context

This job is the payroll backbone for five departments:
FINANCE, OPERATIONS, IT, SALES.  It processes roughly 500–5 000
employees per run.  The total gross disbursed is reported to the
Payroll Controller at job-end.

## Environment

- z/OS 2.5, COBOL for z/OS 6.4
- JCL job class A, 512 MB region
- EMPMASTER: `PAYROLL.EMPMASTR.KSF` (VSAM KSDS)
- DISBFILE:   `PAYROLL.DISB.OUTFILE` (sequential PS)

## No observability yet

This program has no OpenTelemetry instrumentation.  There are no
HTTP calls to an OTel sidecar, no span start/end calls, and no
metrics emission.  It produces only `DISPLAY` statements and a
RETURN-CODE.
