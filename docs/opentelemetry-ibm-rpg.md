# OpenTelemetry for IBM RPG (AS/400) — Complete Guide

> How to get distributed traces out of IBM RPG programs — service programs, interactive jobs, batch RPG, and CL procedures — and into Elastic APM, without touching the IBM i OS configuration or installing any agent on the system.

IBM RPG has no official OpenTelemetry SDK. Neither does any major APM vendor. This guide shows the only practical approach: a telemetry sidecar that RPG programs call via HTTP, using the native `QzhbCgiUtils` or system-level `QSYS/QTMHHTTP` interfaces, or by shelling out to `curl` via `QSYS/QCMDEXC`.

---

## The challenge with IBM i and OpenTelemetry

IBM RPG runs inside the IBM i operating system (formerly AS/400), a vertical stack where OS, database (DB2), and runtime are inseparable. The JVM is available on IBM i, but the OTel Java agent cannot intercept native RPG activation groups. There is no RPG port of the OTel SDK.

What RPG programs can do: execute CL commands, make HTTP calls via IBM i HTTP APIs, and call system programs. That is enough.

---

## Architecture

```
[RPG Program / Service Program / Batch Job]
        |
        | HTTP POST (JSON via QSYS/QTMHHTTP or curl via QSYS/QCMDEXC)
        v
[otel-sidecar :9411]          ← Python, runs on a Linux/AIX host or Docker container
        |
        | OTLP HTTP
        v
[Elastic APM / Elastic Cloud]
```

The RPG program calls the sidecar. The sidecar translates the call into an OTLP span and forwards it to Elastic. The IBM i runtime never handles OTel directly.

---

## Method 1: HTTP via QSYS/QCMDEXC (most compatible)

This works on any IBM i release that has the QShell interpreter (`QSH`). It shells out to `curl`, which ships with IBM i 7.1 and later.

```rpgle
**free

// ─── OTel sidecar: fire-and-forget event via curl / QSH ───────────────────
// Place calls close to business operations, not at the top of the program.

dcl-proc OtelEvent;
  dcl-pi *n;
    pName      varchar(256) const;
    pAttrsJson varchar(4096) const;
  end-pi;

  dcl-s cmd varchar(8192);

  // Build the QSH curl command — single quotes around JSON body avoid escaping hell
  cmd = 'QSH CMD(''curl -sf -X POST http://192.168.1.50:9411' +
        ' -H "Content-Type: application/json"' +
        ' -d "{\"action\":\"event\",\"name\":\"' + %trim(pName) + '\"' +
        ',\"attributes\":' + %trim(pAttrsJson) + '}"' +
        ' >/dev/null 2>&1 || true'')';

  // QCMDEXC is fire-and-forget — errors are suppressed
  monitor;
    CALLP QCMDEXC(cmd : %len(%trim(cmd)));
  on-error;
    // Never let telemetry failures surface to users
  endmon;

end-proc;


// ─── Example: instrument an order processing program ──────────────────────

dcl-s orderId    varchar(20);
dcl-s totalAmt   packed(13:2);
dcl-s custSegment varchar(20);
dcl-s attrsJson  varchar(4096);

// ... existing order processing logic ...

// Emit a telemetry event immediately after the business operation
attrsJson = '{"order.id":"' + %trim(orderId) + '"' +
            ',"order.value_usd":' + %char(totalAmt) +
            ',"customer.segment":"' + %trim(custSegment) + '"' +
            ',"job.name":"' + %trim(%jobname()) + '"' +
            ',"job.number":"' + %trim(%jobnbr()) + '"' +
            ',"library":"ORDLIB"}';

OtelEvent('order.processed' : attrsJson);
```

---

## Method 2: HTTP via IBM i Integrated Web Services (IWS)

On IBM i 7.2+, you can use the integrated HTTP client API without spawning a shell process. This is faster and more reliable for high-volume programs.

```rpgle
**free

// Uses IBM i IWS HTTP client (available 7.2+)
// Requires *JOBCTL special authority is NOT needed — just HTTP outbound access

ctl-opt nomain;

dcl-proc OtelEvent export;
  dcl-pi *n;
    pName      varchar(256) const;
    pAttrsJson varchar(4096) const;
  end-pi;

  dcl-s body    varchar(8192);
  dcl-s bodyLen int(10);
  dcl-s url     varchar(512);

  // Build JSON body
  body = '{"action":"event","name":"' + %trim(pName) + '"' +
         ',"attributes":' + %trim(pAttrsJson) + '}';
  bodyLen = %len(%trim(body));
  url = 'http://192.168.1.50:9411';

  // Call the IWS HTTP POST procedure
  // (Prototype for QtmhWrStdin / QtmhRdStdin pattern omitted for brevity —
  //  use the QzhbCgiUtils service program available in 5770-DG1)
  monitor;
    // callp YOUR_HTTP_POST_PROC(url : body : bodyLen);
    // ↑ Replace with your site's IWS HTTP wrapper or use Method 1 instead
  on-error;
    // Suppress — telemetry failures must never impact business processes
  endmon;

end-proc;
```

> **Practical note:** Most IBM i shops use Method 1 (curl via QCMDEXC) because it works on all releases and requires no additional licensed programs. Method 2 is worth the setup effort for programs that run more than ~100 times per hour.

---

## Method 3: RPG + CL caller for long-running jobs (start_span / end_span)

For batch jobs that run for minutes or hours, fire-and-forget events miss the actual duration. Use start/end span pairs.

```rpgle
**free

// Long-running job: use start_span / end_span to capture real duration

dcl-proc OtelStartSpan;
  dcl-pi *n varchar(36);    // returns span_id
    pName      varchar(256) const;
    pAttrsJson varchar(4096) const;
  end-pi;

  dcl-s spanId  varchar(36);
  dcl-s cmd     varchar(8192);
  dcl-s tmpFile varchar(128);

  // Generate a simple span ID from timestamp + job number
  spanId = %char(%timestamp() : *iso) + '-' + %trim(%jobnbr());

  // Start the span — sidecar will hold it open until end_span
  cmd = 'QSH CMD(''curl -sf -X POST http://192.168.1.50:9411' +
        ' -H "Content-Type: application/json"' +
        ' -d "{\"action\":\"start_span\"' +
        ',\"span_id\":\"' + %trim(spanId) + '\"' +
        ',\"name\":\"' + %trim(pName) + '\"' +
        ',\"attributes\":' + %trim(pAttrsJson) + '}"' +
        ' >/dev/null 2>&1'')';

  monitor;
    CALLP QCMDEXC(cmd : %len(%trim(cmd)));
  on-error;
  endmon;

  return spanId;

end-proc;


dcl-proc OtelEndSpan;
  dcl-pi *n;
    pSpanId    varchar(36) const;
    pAttrsJson varchar(4096) const;
    pError     varchar(512) const options(*nopass);
  end-pi;

  dcl-s errorPart varchar(600);
  dcl-s cmd       varchar(8192);

  if %parms() >= 3 and pError <> '';
    errorPart = ',\"error\":\"' + %trim(pError) + '\"';
  else;
    errorPart = '';
  endif;

  cmd = 'QSH CMD(''curl -sf -X POST http://192.168.1.50:9411' +
        ' -H "Content-Type: application/json"' +
        ' -d "{\"action\":\"end_span\"' +
        ',\"span_id\":\"' + %trim(pSpanId) + '\"' +
        ',\"attributes\":' + %trim(pAttrsJson) +
        %trim(errorPart) + '}"' +
        ' >/dev/null 2>&1'')';

  monitor;
    CALLP QCMDEXC(cmd : %len(%trim(cmd)));
  on-error;
  endmon;

end-proc;
```

**Usage in a batch RPG job:**

```rpgle
**free

// Example: payroll batch job with OTel instrumentation

dcl-s spanId   varchar(36);
dcl-s empCount packed(9:0);
dcl-s totalPay packed(13:2);

spanId = OtelStartSpan('payroll.batch.run' :
         '{"job.schedule":"weekly","pay_period":"' + payPeriod + '"}');

// ... existing payroll processing logic ...

// If an error occurred:
// OtelEndSpan(spanId :
//   '{"employees.processed":' + %char(empCount) + '}' :
//   'DB2 error: ' + %trim(sqlstt));

// On success:
OtelEndSpan(spanId :
  '{"employees.processed":' + %char(empCount) +
  ',"total.payroll_usd":' + %char(totalPay) +
  ',"run.duration_s":' + %char(runSeconds) + '}');
```

---

## CL caller (for CL procedures that call RPG)

Many IBM i shops have CL procedures that orchestrate RPG programs. You can emit telemetry directly from CL:

```cl
/* CL Procedure: emit telemetry from CL programs */
PGM

DCL VAR(&CMD) TYPE(*CHAR) LEN(2048)
DCL VAR(&JOBNAME) TYPE(*CHAR) LEN(10)
DCL VAR(&JOBNBR) TYPE(*CHAR) LEN(6)

RTVJOBA JOB(&JOBNAME) NBR(&JOBNBR)

/* Build curl command */
CHGVAR VAR(&CMD) VALUE('curl -sf -X POST http://192.168.1.50:9411 +
  -H "Content-Type: application/json" +
  -d "{\"action\":\"event\",\"name\":\"cl.job.complete\", +
  \"attributes\":{\"job.name\":\"' *CAT &JOBNAME *CAT '\", +
  \"job.number\":\"' *CAT &JOBNBR *CAT '\"}}" +
  >/dev/null 2>&1 || true')

/* Run via QSH — errors are suppressed */
QSH CMD(&CMD)

ENDPGM
```

---

## Running the sidecar on IBM i infrastructure

The sidecar does not run on IBM i — it runs on a Linux system or Docker container that the IBM i server can reach on the network. The RPG programs call it by IP address (or hostname if DNS is configured).

### Option A: Linux host on the same network

```bash
export OTEL_SERVICE_NAME=ibm-i-production
export ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io
export ELASTIC_API_KEY=<your-api-key>
export SIDECAR_PORT=9411

python3 otel-sidecar.py &
```

The IBM i server must have outbound network access to the Linux host on port 9411.

### Option B: Docker container

```yaml
services:
  otel-sidecar:
    image: gmoskovicz/edot-autopilot-sidecar:latest
    ports:
      - "9411:9411"          # IBM i programs call this IP:9411
    environment:
      OTEL_SERVICE_NAME:    ibm-i-production
      ELASTIC_OTLP_ENDPOINT: ${ELASTIC_OTLP_ENDPOINT}
      ELASTIC_API_KEY:       ${ELASTIC_API_KEY}
    restart: unless-stopped
```

> **Network note:** If your IBM i is on a private network segment, the Docker container must be on the same segment or routable from it. `network_mode: host` works if the container host is on the IBM i network.

---

## What to instrument in IBM RPG

Focus on operations with business impact:

| Program type | Span name pattern | Key attributes |
|---|---|---|
| Order entry (interactive) | `order.entry.complete` | `order.id`, `order.value`, `customer.number` |
| Batch job step | `batch.job.step` | `job.name`, `job.number`, `rows.processed` |
| DB2 stored procedure | `db2.proc.call` | `proc.name`, `rows.affected`, `duration_ms` |
| Payroll run | `payroll.batch.run` | `pay_period`, `employees.processed`, `total.payroll_usd` |
| EDI processing | `edi.document.process` | `edi.type`, `trading.partner`, `document.count` |
| MFG work order | `mfg.work_order.close` | `work_order.number`, `part.number`, `qty.produced` |

**Key attributes for IBM i observability:**
- `ibm_i.job_name` — the IBM i job name (e.g., `QBATCH`)
- `ibm_i.job_number` — the job number (unique per run)
- `ibm_i.user` — the job user profile (hash for PII compliance)
- `ibm_i.library` — the library the program was called from
- `ibm_i.subsystem` — the subsystem (QBATCH, QINTER, etc.)
- `ibm_i.release` — the OS release (e.g., `V7R5M0`)

---

## Verifying in Elastic APM

After the sidecar is running and your RPG program executes:

1. Open Kibana → Observability → APM → Services
2. Look for the service named by `OTEL_SERVICE_NAME` (e.g., `ibm-i-production`)
3. Navigate to Transactions → find your span names (e.g., `payroll.batch.run`)
4. Confirm business attributes are present: `pay_period`, `employees.processed`, etc.

---

## Troubleshooting

**"curl: command not found" on IBM i**

curl ships with IBM i 7.1+ in the 5733-SC1 option. To verify:
```
CALL PGM(QSYS/QCMDEXC) PARM('QSH CMD(''which curl'')' 0000000021)
```

If curl is unavailable, use the QzhbCgiUtils IBM i HTTP API (Method 2) or request the 5733-SC1 option from your IBM i administrator.

**Spans appear in APM but attributes are missing**

This usually means the JSON body was malformed. Test with a known-good curl command from QSH directly:
```
QSH CMD('curl -sf -X POST http://192.168.1.50:9411 -H "Content-Type: application/json" -d "{\"action\":\"event\",\"name\":\"test\",\"attributes\":{\"test\":\"ok\"}}"')
```

**Job hangs waiting for curl**

Add `-m 1` to curl (1-second timeout): `-sf -m 1 -X POST ...`. The `|| true` at the end ensures the job continues even if curl fails.

---

## Related guides

- [OpenTelemetry for SAP ABAP](opentelemetry-sap-abap.md) — the same sidecar pattern for SAP ABAP programs
- [OpenTelemetry for COBOL](opentelemetry-cobol.md) — mainframe batch job instrumentation
- [Telemetry Sidecar Pattern](telemetry-sidecar-pattern.md) — full sidecar documentation
- [Business Span Enrichment](business-span-enrichment.md) — what attributes to capture

---

*Part of [EDOT Autopilot](https://github.com/gmoskovicz/edot-autopilot) — OpenTelemetry autopilot for any codebase.*
