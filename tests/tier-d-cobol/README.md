# Tier D — COBOL

COBOL has no OpenTelemetry SDK. It likely never will. But COBOL can call `SYSTEM` to execute shell commands — including `curl`. That's the entire integration.

## The pattern

```cobol
       MOVE "order.processed" TO WS-SPAN-NAME
       STRING
           'curl -sf -X POST http://127.0.0.1:9411'
           ' -H "Content-Type: application/json"'
           ' -d "{\"action\":\"event\",\"name\":\"' WS-SPAN-NAME '\",'
           '\"attributes\":{\"order.id\":\"' WS-ORDER-ID '\",'
           '\"order.value_usd\":' WS-AMOUNT-STR '}}"'
           ' > /dev/null 2>&1 || true'
           DELIMITED SIZE INTO WS-CURL-CMD
       CALL "SYSTEM" USING WS-CURL-CMD
```

The `|| true` ensures the COBOL program continues even if the sidecar is down.

## Platforms where this works

- **IBM z/OS** with Unix System Services (USS) — curl available
- **IBM AIX** — curl available
- **Linux** (GnuCOBOL) — curl available
- **AS/400 (IBM i)** — see `../tier-d-ibm-as400/` for QSHELL approach

## Compile and run (GnuCOBOL)

```bash
# Install GnuCOBOL
brew install gnu-cobol   # macOS
apt install open-cobol   # Debian/Ubuntu

# Start the sidecar first
cd ../../otel-sidecar
OTEL_SERVICE_NAME=cobol-tier-d docker compose up -d

# Compile and run
cobc -x demo.cob -o otel-demo
./otel-demo
```

## Verify in Elastic

Kibana → Observability → APM → Services → `cobol-tier-d`

You'll see spans with `order.id`, `order.value_usd`, and `customer.tier` — business data that no other observability tool can extract from COBOL without source code access.
