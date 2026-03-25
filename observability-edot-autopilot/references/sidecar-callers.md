# Telemetry Sidecar — Caller Snippets

The sidecar runs at `http://127.0.0.1:9411` (configurable via `SIDECAR_PORT`).
All calls are fire-and-forget: never let a telemetry failure block business logic.

## Sidecar API

```
POST /
Content-Type: application/json

Actions:
  {"action": "event", "name": "span.name", "attributes": {}, "error": "optional msg"}
  {"action": "start_span", "name": "span.name", "span_id": "my-id", "traceparent": "00-..."}
  {"action": "end_span", "span_id": "my-id", "attributes": {}, "error": "optional"}
  {"action": "health"}
```

---

## COBOL

```cobol
      *----------------------------------------------------------------
      * OTEL-EVENT — emit a single telemetry event via sidecar
      * Call: MOVE "span.name" TO WS-SPAN-NAME
      *        MOVE "{""key"":""val""}" TO WS-ATTR-JSON
      *        PERFORM OTEL-EVENT
      *----------------------------------------------------------------
       01 WS-OTEL.
          05 WS-SPAN-NAME   PIC X(80).
          05 WS-ATTR-JSON   PIC X(512) VALUE "{}".
          05 WS-CURL-CMD    PIC X(1024).
          05 WS-ORDER-ID    PIC X(36).

       OTEL-EVENT.
           STRING 'curl -sf -X POST http://127.0.0.1:9411'
                  ' -H "Content-Type: application/json"'
                  ' -d "{\"action\":\"event\",\"name\":\"'
                  WS-SPAN-NAME
                  '\",\"attributes\":'
                  WS-ATTR-JSON
                  '}"'
                  DELIMITED SIZE INTO WS-CURL-CMD
           CALL "SYSTEM" USING WS-CURL-CMD
           EXIT.

      * Usage example:
       MOVE "order.processed" TO WS-SPAN-NAME
       MOVE "{""order.id"":""ORD-001"",""order.value_usd"":249.99}"
            TO WS-ATTR-JSON
       PERFORM OTEL-EVENT
```

---

## Perl

```perl
use LWP::UserAgent;
use JSON;

my $ua = LWP::UserAgent->new(timeout => 1);

sub otel_event {
    my ($name, %attrs) = @_;
    eval {
        $ua->post('http://127.0.0.1:9411',
            'Content-Type' => 'application/json',
            Content => encode_json({
                action     => 'event',
                name       => $name,
                attributes => \%attrs,
            })
        );
    };
    # silently ignore errors — telemetry must never block business logic
}

sub otel_start_span {
    my ($name, $span_id, %attrs) = @_;
    my $resp = eval {
        $ua->post('http://127.0.0.1:9411',
            'Content-Type' => 'application/json',
            Content => encode_json({
                action     => 'start_span',
                name       => $name,
                span_id    => $span_id,
                attributes => \%attrs,
            })
        );
    };
    return $resp ? decode_json($resp->content)->{traceparent} : undef;
}

sub otel_end_span {
    my ($span_id, $error, %attrs) = @_;
    eval {
        $ua->post('http://127.0.0.1:9411',
            'Content-Type' => 'application/json',
            Content => encode_json({
                action     => 'end_span',
                span_id    => $span_id,
                error      => $error,
                attributes => \%attrs,
            })
        );
    };
}

# Usage
otel_event('invoice.sent',
    invoice_id => $invoice_id,
    amount     => $total,
    customer   => $customer_id,
    currency   => 'USD',
);
```

---

## Bash / Shell

```bash
#!/usr/bin/env bash

OTEL_SIDECAR_URL="${OTEL_SIDECAR_URL:-http://127.0.0.1:9411}"

# Emit a single-shot span
otel_event() {
    local name="$1"
    local attrs="${2:-{}}"
    local error="${3:-}"
    local body="{\"action\":\"event\",\"name\":\"$name\",\"attributes\":$attrs}"
    [ -n "$error" ] && body="{\"action\":\"event\",\"name\":\"$name\",\"attributes\":$attrs,\"error\":\"$error\"}"
    curl -sf -X POST "$OTEL_SIDECAR_URL" \
        -H "Content-Type: application/json" \
        -d "$body" >/dev/null 2>&1 || true  # never block the script
}

# Start a multi-step span (returns traceparent)
otel_start_span() {
    local name="$1"
    local span_id="$2"
    local attrs="${3:-{}}"
    curl -sf -X POST "$OTEL_SIDECAR_URL" \
        -H "Content-Type: application/json" \
        -d "{\"action\":\"start_span\",\"name\":\"$name\",\"span_id\":\"$span_id\",\"attributes\":$attrs}" \
        2>/dev/null | grep -o '"traceparent":"[^"]*"' | cut -d'"' -f4 || echo ""
}

# End a multi-step span
otel_end_span() {
    local span_id="$1"
    local error="${2:-}"
    local attrs="${3:-{}}"
    local body="{\"action\":\"end_span\",\"span_id\":\"$span_id\",\"attributes\":$attrs}"
    [ -n "$error" ] && body="{\"action\":\"end_span\",\"span_id\":\"$span_id\",\"error\":\"$error\",\"attributes\":$attrs}"
    curl -sf -X POST "$OTEL_SIDECAR_URL" \
        -H "Content-Type: application/json" \
        -d "$body" >/dev/null 2>&1 || true
}

# Usage — single event
otel_event "backup.complete" \
    '{"size_mb":2048,"duration_s":34,"destination":"s3://backups/prod"}'

# Usage — multi-step span
SPAN_ID="etl-batch-$(date +%s)"
otel_start_span "etl.batch.process" "$SPAN_ID" \
    '{"batch.source":"legacy-erp","batch.date":"2024-01-15"}'

# ... do work ...

otel_end_span "$SPAN_ID" "" \
    '{"batch.records_processed":50000,"batch.duration_ms":4200}'
```

---

## PowerShell

```powershell
$OtelSidecarUrl = $env:OTEL_SIDECAR_URL ?? "http://127.0.0.1:9411"

function Send-OtelEvent {
    param(
        [string]$Name,
        [hashtable]$Attributes = @{},
        [string]$Error = ""
    )
    try {
        $body = @{action='event'; name=$Name; attributes=$Attributes}
        if ($Error) { $body['error'] = $Error }
        Invoke-RestMethod -Uri $OtelSidecarUrl -Method Post `
            -ContentType "application/json" `
            -TimeoutSec 1 `
            -Body ($body | ConvertTo-Json -Compress) | Out-Null
    } catch {} # never block the script
}

function Start-OtelSpan {
    param([string]$Name, [string]$SpanId, [hashtable]$Attributes = @{})
    try {
        $body = @{action='start_span'; name=$Name; span_id=$SpanId; attributes=$Attributes}
        $resp = Invoke-RestMethod -Uri $OtelSidecarUrl -Method Post `
            -ContentType "application/json" -TimeoutSec 1 `
            -Body ($body | ConvertTo-Json -Compress)
        return $resp.traceparent
    } catch { return $null }
}

function End-OtelSpan {
    param([string]$SpanId, [string]$Error = "", [hashtable]$Attributes = @{})
    try {
        $body = @{action='end_span'; span_id=$SpanId; attributes=$Attributes}
        if ($Error) { $body['error'] = $Error }
        Invoke-RestMethod -Uri $OtelSidecarUrl -Method Post `
            -ContentType "application/json" -TimeoutSec 1 `
            -Body ($body | ConvertTo-Json -Compress) | Out-Null
    } catch {}
}

# Usage
Send-OtelEvent "etl.batch.complete" @{
    rows         = 50000
    duration_ms  = 4200
    source       = "legacy-erp"
    destination  = "data-warehouse"
}
```

---

## Classic ASP / VBScript

```vbscript
<%
Function OtelEvent(spanName, attrsJson)
    On Error Resume Next
    Dim http
    Set http = Server.CreateObject("MSXML2.ServerXMLHTTP")
    http.setTimeouts 1000, 1000, 1000, 1000
    http.open "POST", "http://127.0.0.1:9411", False
    http.setRequestHeader "Content-Type", "application/json"
    http.send "{""action"":""event"",""name"":""" & spanName & _
              """,""attributes"":" & attrsJson & "}"
    Set http = Nothing
    On Error GoTo 0
End Function

' Usage
OtelEvent "invoice.generated", _
    "{""invoice_id"":""INV-2024-001"",""amount"":4500,""customer_id"":""CUST-789""}"
%>
```

---

## Ruby (legacy / no OTel gem available)

```ruby
require 'net/http'
require 'json'
require 'uri'

SIDECAR_URL = URI.parse(ENV.fetch('OTEL_SIDECAR_URL', 'http://127.0.0.1:9411'))

def otel_event(name, attributes = {}, error: nil)
  payload = { action: 'event', name: name, attributes: attributes }
  payload[:error] = error if error
  http = Net::HTTP.new(SIDECAR_URL.host, SIDECAR_URL.port)
  http.open_timeout = 1
  http.read_timeout = 1
  http.post('/', payload.to_json, 'Content-Type' => 'application/json')
rescue StandardError
  nil  # never block business logic
end

# Usage
otel_event('order.shipped',
  { 'order.id' => order_id, 'shipping.carrier' => 'UPS', 'shipping.days' => 3 }
)
```

---

## PHP 5 / legacy PHP

```php
<?php
function otelEvent($name, $attributes = [], $error = null) {
    $payload = json_encode([
        'action'     => 'event',
        'name'       => $name,
        'attributes' => $attributes,
        'error'      => $error,
    ]);
    $url = getenv('OTEL_SIDECAR_URL') ?: 'http://127.0.0.1:9411';

    // Works with PHP 5.2+
    $opts = ['http' => [
        'method'  => 'POST',
        'header'  => "Content-Type: application/json\r\n",
        'content' => $payload,
        'timeout' => 1,
        'ignore_errors' => true,
    ]];
    @file_get_contents($url, false, stream_context_create($opts));
}

// Usage
otelEvent('payment.processed', [
    'order_id'   => $orderId,
    'amount_usd' => $amount,
    'method'     => $paymentMethod,
]);
?>
```

---

## Python (legacy / no OTel SDK available)

```python
import json, urllib.request, os

_SIDECAR = os.environ.get("OTEL_SIDECAR_URL", "http://127.0.0.1:9411")

def otel_event(name, attributes=None, error=None):
    payload = {"action": "event", "name": name, "attributes": attributes or {}}
    if error:
        payload["error"] = str(error)
    try:
        req = urllib.request.Request(
            _SIDECAR,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass  # never block business logic

# Usage (works on Python 2.7 and 3.x)
otel_event("report.generated", {
    "report.type": "monthly-sales",
    "report.rows": 1420,
    "report.format": "xlsx",
})
```

---

## curl (any language that can shell out)

```bash
# Generic one-liner — embed in any language that supports shell execution
curl -sf -X POST http://127.0.0.1:9411 \
  -H "Content-Type: application/json" \
  -d '{"action":"event","name":"job.complete","attributes":{"job":"payroll","rows":8200}}' \
  >/dev/null 2>&1 || true
```
