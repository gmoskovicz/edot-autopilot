# Tier D — IBM AS/400 (IBM i / iSeries)

IBM AS/400 (now called IBM i) runs RPG IV, CL, and COBOL. None have OpenTelemetry SDKs. But IBM i has QSHELL (Unix-like shell) with curl, and can call external HTTP services from RPG via the ILE HTTP API.

## Strategy 1: QSHELL + curl (simplest)

From any CL program, call QSHELL to send telemetry:

```cl
/* CL Program */
PGM
  DCL VAR(&CMD) TYPE(*CHAR) LEN(512)
  DCL VAR(&ORDERID) TYPE(*CHAR) LEN(20) VALUE('ORD-001')
  DCL VAR(&AMOUNT) TYPE(*CHAR) LEN(12) VALUE('4200.00')

  /* Build curl command */
  CHGVAR VAR(&CMD) VALUE('curl -sf -X POST http://127.0.0.1:9411 ' +
    '-H "Content-Type: application/json" ' +
    '-d "{\"action\":\"event\",\"name\":\"order.processed\",' +
    '\"attributes\":{\"order.id\":\"' *CAT &ORDERID *CAT '\",' +
    '\"order.value_usd\":' *CAT &AMOUNT *CAT '}}" > /dev/null 2>&1 || true')

  /* Execute via QSHELL — never fail the business program */
  MONMSG MSGID(CPF0000)
  CALL PGM(QSHELL) PARM('/bin/sh' '-c' &CMD)
ENDPGM
```

## Strategy 2: RPG with HTTP API (ILE sockets)

For environments where QSHELL is unavailable, RPG IV can make raw TCP socket calls:

```rpgle
**FREE
// RPG IV — Emit OTel event via HTTP socket
dcl-pr OtelEvent extproc('otel_event');
  name  varchar(100) value;
  attrs varchar(500) value;
end-pr;

// In your order processing procedure:
OtelEvent('order.processed':
          '{"order.id":"' + orderId + '",' +
          '"order.value_usd":' + %char(orderAmount) + ',' +
          '"customer.tier":"enterprise"}');
```

The `otel_event` C service program (compiled separately):
```c
#include <sys/socket.h>
#include <netinet/in.h>
#include <string.h>

void otel_event(char *name, char *attrs) {
    // Build JSON and POST to sidecar at 127.0.0.1:9411
    // Full implementation in otel_sidecar_c.c
}
```

## Strategy 3: DB2 for i external procedure

IBM i DB2 can call external programs. Create a wrapper stored procedure:

```sql
-- Call from any SQL program, trigger, or stored procedure
CALL QSYS2.QSHELL(
  'curl -sf -X POST http://127.0.0.1:9411 '
  || '-H "Content-Type: application/json" '
  || '-d ''{"action":"event","name":"db2.batch.complete","attributes":{"rows":50000}}'' '
  || '>/dev/null 2>&1 || true'
);
```

## Deployment

1. Run the otel-sidecar on the AS/400 PASE environment (Python available in PASE)
2. Or run the sidecar on a separate Linux server on the same network
3. Configure `SIDECAR_HOST=0.0.0.0` to listen on the network interface

```bash
# PASE shell on IBM i
pip3 install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
OTEL_SERVICE_NAME=ibm-as400 \
ELASTIC_OTLP_ENDPOINT=https://YOUR-DEPLOYMENT.ingest.REGION.gcp.elastic.cloud:443 \
ELASTIC_API_KEY=your-key \
python3 /opt/otel-sidecar/otel-sidecar.py &
```

## What you get in Elastic APM

- Order processing rates from AS/400 ERP
- Batch job execution spans with row counts
- Cross-system traces: AS/400 order → Java microservice → payment gateway
- Alerts when the nightly batch job doesn't complete on time
