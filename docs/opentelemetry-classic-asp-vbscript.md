# OpenTelemetry for Classic ASP / VBScript — Complete Guide

> How to get distributed traces out of Classic ASP (VBScript) applications running on IIS and into Elastic APM — without touching or rewriting a single page.

## The problem

Classic ASP — the original Active Server Pages built on VBScript and JScript — was released in 1996 and reached end-of-life in 2002. Yet it still runs in production at a significant number of enterprises, particularly in:

- **Finance and insurance**: policy administration systems, actuarial calculation tools, broker portals built before .NET existed
- **Manufacturing and distribution**: ERP front-ends, inventory management systems, order entry portals
- **Government**: case management systems, licensing portals, permit tracking applications
- **Healthcare**: patient scheduling systems, billing portals, lab result interfaces
- **E-commerce**: shopping carts and catalog systems built in the early 2000s that "work fine" and never got rewritten

The reason these applications survive is the same reason they are blind spots: they work. Nobody wants to touch them. The business cannot afford the risk of a full rewrite. The original developers are often long gone. The codebase is often thousands of `.asp` files with no tests.

And because no APM vendor supports Classic ASP — there is no agent, no SDK, no plugin for IIS-hosted VBScript — these applications are completely invisible when performance degrades or errors occur.

Classic ASP errors often manifest silently: VBScript's `On Error Resume Next` is used everywhere, so a page that fails may still return HTTP 200 with empty content. By the time support tickets pile up, it can be very hard to trace back the root cause.

## The solution: Telemetry Sidecar

The EDOT Autopilot telemetry sidecar runs as a local HTTP server on port 9411 on the same Windows host as IIS. Classic ASP pages use `MSXML2.ServerXMLHTTP` — a COM object available on every Windows/IIS installation since Windows 2000 — to POST events to the sidecar. The sidecar translates those events into OTLP spans and forwards them to Elastic.

Architecture:

```
[Classic ASP Page on IIS]
    |
    | MSXML2.ServerXMLHTTP POST http://127.0.0.1:9411
    |
    v
[otel-sidecar.py :9411]   (Python, same Windows host)
    |
    | OTLP/HTTP
    v
[Elastic Cloud APM]
```

Because the sidecar binds only to `127.0.0.1`, it is not reachable from outside the host. The IIS worker process calls it in-process on the loopback interface — round-trip is typically under 5ms.

## Step-by-step setup

### Step 1: Install Python on the IIS host

```powershell
winget install Python.Python.3.12
```

Or download from python.org. Python must be installed on the same Windows server running IIS.

### Step 2: Install sidecar dependencies

```powershell
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
```

### Step 3: Clone the repo

```powershell
git clone https://github.com/gmoskovicz/edot-autopilot C:\opt\edot-autopilot
```

### Step 4: Install the sidecar as a Windows service

Use NSSM (Non-Sucking Service Manager) — downloadable from nssm.cc:

```powershell
nssm install OtelSidecar "C:\Python312\python.exe" "C:\opt\edot-autopilot\otel-sidecar\otel-sidecar.py"
nssm set OtelSidecar AppEnvironmentExtra "OTEL_SERVICE_NAME=classic-asp-portal"
nssm set OtelSidecar AppEnvironmentExtra+ "ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io"
nssm set OtelSidecar AppEnvironmentExtra+ "ELASTIC_API_KEY=<your-key>"
nssm set OtelSidecar AppEnvironmentExtra+ "OTEL_DEPLOYMENT_ENVIRONMENT=production"
nssm set OtelSidecar Start SERVICE_AUTO_START
nssm start OtelSidecar
```

Verify:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:9411 -Method Post `
  -ContentType 'application/json' `
  -Body '{"action":"event","name":"sidecar.test","attributes":{"test":"true"}}'
# Expected: @{ok=True}
```

### Step 5: Create a shared include file

Create a file `/_includes/telemetry.asp` with the `OtelEvent` subroutine. Include it at the top of pages you want to instrument with `<!--#include file="/_includes/telemetry.asp"-->`.

### Step 6: Add telemetry calls near business events

Add calls immediately after the actions that matter — invoice generation, order submission, payment processing — not at the top of the file.

## Code example

### Shared include file: `/_includes/telemetry.asp`

```vbscript
<%
' OtelEvent — emit a telemetry event to the local sidecar
' Usage: OtelEvent "invoice.generated", "{""id"":""INV-001"",""amount"":4500}"
Sub OtelEvent(spanName, attrsJson)
    On Error Resume Next
    Dim h
    Set h = Server.CreateObject("MSXML2.ServerXMLHTTP")
    If Err.Number <> 0 Then Exit Sub

    h.open "POST", "http://127.0.0.1:9411", False
    h.setRequestHeader "Content-Type", "application/json"
    h.setTimeouts 0, 1000, 1000, 1000   ' resolveTimeout, connectTimeout, sendTimeout, receiveTimeout (ms)

    Dim payload
    payload = "{""action"":""event"",""name"":""" & spanName & """," & _
              """attributes"":" & attrsJson & "}"

    h.send payload
    Set h = Nothing
    Err.Clear
    On Error GoTo 0
End Sub
%>
```

### Invoice generation page

```vbscript
<%
<!--#include file="/_includes/telemetry.asp"-->

Dim invoiceId, customerId, amount, invoiceStatus

' ... retrieve order data from database ...
invoiceId  = RS("invoice_id")
customerId = RS("customer_id")
amount     = RS("amount")

' ... generate the invoice ...
Call GenerateInvoicePDF(invoiceId)
Call SendInvoiceEmail(customerId, invoiceId)

invoiceStatus = "sent"

' Emit telemetry after successful invoice dispatch
OtelEvent "invoice.generated", _
    "{""invoice.id"":""" & invoiceId & """," & _
    """customer.id"":""" & customerId & """," & _
    """invoice.amount"":" & amount & "," & _
    """invoice.status"":""" & invoiceStatus & """}"
%>
```

### Order submission handler

```vbscript
<%
<!--#include file="/_includes/telemetry.asp"-->

Dim orderId, userId, total, itemCount, paymentMethod

orderId       = Request.Form("order_id")
userId        = Session("user_id")
total         = CDbl(Request.Form("total"))
itemCount     = CInt(Request.Form("item_count"))
paymentMethod = Request.Form("payment_method")

' ... process the order ...
Dim success
success = ProcessOrder(orderId, userId)

If success Then
    OtelEvent "order.submitted", _
        "{""order.id"":""" & orderId & """," & _
        """user.id"":""" & userId & """," & _
        """order.value_usd"":" & total & "," & _
        """order.item_count"":" & itemCount & "," & _
        """payment.method"":""" & paymentMethod & """}"

    Response.Redirect "/order-confirmation.asp?id=" & orderId
Else
    OtelEvent "order.submission.failed", _
        "{""order.id"":""" & orderId & """," & _
        """user.id"":""" & userId & """," & _
        """error"":""ProcessOrder returned false""}"

    Response.Write "Order failed. Please try again."
End If
%>
```

### Payment processing with error capture

```vbscript
<%
<!--#include file="/_includes/telemetry.asp"-->

On Error Resume Next

Dim chargeId, customerId, amount, currency, errorMsg
customerId = Session("customer_id")
amount     = CDbl(Request.Form("amount"))
currency   = "USD"

' Attempt payment
Call ChargeCustomer(customerId, amount, currency, chargeId)

If Err.Number <> 0 Then
    errorMsg = Err.Description
    OtelEvent "payment.failed", _
        "{""customer.id"":""" & customerId & """," & _
        """payment.amount"":" & amount & "," & _
        """payment.currency"":""" & currency & """," & _
        """error.message"":""" & Replace(errorMsg, """", "'") & """}"
    Err.Clear
    ' Handle error...
Else
    OtelEvent "payment.authorized", _
        "{""customer.id"":""" & customerId & """," & _
        """payment.charge_id"":""" & chargeId & """," & _
        """payment.amount"":" & amount & "," & _
        """payment.currency"":""" & currency & """}"
End If

On Error GoTo 0
%>
```

### Page-level request tracking (global.asa or Application_OnStart)

To track all page requests, add a `Session_OnStart` handler in `global.asa`:

```vbscript
' global.asa
<SCRIPT LANGUAGE="VBScript" RUNAT="Server">
Sub Session_OnStart
    ' Session start tracking
    Dim h
    Set h = Server.CreateObject("MSXML2.ServerXMLHTTP")
    If Err.Number = 0 Then
        h.open "POST", "http://127.0.0.1:9411", False
        h.setRequestHeader "Content-Type", "application/json"
        h.setTimeouts 0, 500, 500, 500
        h.send "{""action"":""event"",""name"":""session.started"",""attributes"":{""session.id"":""" & Session.SessionID & """}}"
        Set h = Nothing
    End If
End Sub
</SCRIPT>
```

## What you'll see in Elastic

After deploying the sidecar and adding instrumentation:

- **Named service** in Kibana APM: `classic-asp-portal` (or whatever you set in `OTEL_SERVICE_NAME`).
- **Business event spans**: `invoice.generated`, `order.submitted`, `payment.authorized` — named after what your Classic ASP pages actually do.
- **Error tracking**: Errors with `On Error Resume Next` that previously vanished silently now appear in Kibana's Errors tab with context.
- **Request volume trends**: How many orders/invoices/payments are processed per hour, day, and week.
- **Custom attributes as searchable fields**: `customer.id`, `order.value_usd`, `invoice.amount` are all filterable in Kibana Discover.

Example ES|QL query to analyze order submission failures:

```esql
FROM traces-apm*
| WHERE service.name == "classic-asp-portal"
  AND span.name == "order.submission.failed"
| STATS count = COUNT(*) BY bin(@timestamp, 1h)
| SORT @timestamp DESC
```

## Related

- [Telemetry Sidecar Pattern — full documentation](./telemetry-sidecar-pattern.md)
- [OpenTelemetry for Legacy Runtimes — overview](./opentelemetry-legacy-runtimes.md)
- [OpenTelemetry for .NET Framework 4.x](./opentelemetry-dotnet-framework-4x.md)
- [Business Span Enrichment](./business-span-enrichment.md)
- [otel-sidecar.py source](../otel-sidecar/otel-sidecar.py)

---

> Found this useful? [Star the repo](https://github.com/gmoskovicz/edot-autopilot) — it helps other Classic ASP / VBScript developers find this solution.
