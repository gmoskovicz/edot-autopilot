# OpenTelemetry for .NET Framework 4.x — Complete Guide

> How to instrument .NET Framework 4.x applications — WebForms, WCF, MVC 5, Windows Services — with OpenTelemetry and ship traces to Elastic APM.

## The problem

The Elastic EDOT .NET SDK targets .NET 6 and later. The official OpenTelemetry .NET auto-instrumentation also targets .NET 6+. This leaves a large category of enterprise applications without automatic support:

- **ASP.NET WebForms** (.NET Framework 4.x) — millions of enterprise web apps
- **WCF services** (.NET Framework 4.x) — used extensively in SOA-era enterprise architectures
- **ASP.NET MVC 4 / MVC 5** — pre-Core MVC applications
- **Windows Services** (.NET Framework 4.x) — background workers, scheduled processors
- **Console applications** (.NET Framework 4.x) — batch jobs, data loaders

Many of these applications process business-critical transactions: payment processing, order fulfillment, insurance claims, loan origination. They are not being rewritten — not this year, and possibly not ever. They run on Windows Server, they target `net462` or `net48`, and they are not going anywhere.

The good news: the OpenTelemetry .NET SDK itself (not the EDOT wrapper) supports .NET Framework 4.6.2 and later. This means you can instrument .NET Framework 4.x applications manually — by initializing the TracerProvider at startup and wrapping entry points with spans — without auto-instrumentation.

This is what the EDOT Autopilot calls a **Tier B** application: the language runtime is supported, but the framework is not covered by zero-config auto-instrumentation. The solution is manual wrapping.

## The solution: Manual span wrapping with the OTel .NET SDK

Unlike Tier D languages (COBOL, Perl, Bash) that require a sidecar, .NET Framework 4.x can use the OpenTelemetry .NET SDK directly. You initialize a `TracerProvider` once at application startup and use it to create spans around your entry points.

The OpenTelemetry .NET SDK packages that support .NET Framework 4.6.2+ are:
- `OpenTelemetry` (core SDK)
- `OpenTelemetry.Exporter.OpenTelemetryProtocol` (OTLP exporter for Elastic)
- `OpenTelemetry.Extensions.Hosting` (optional, for DI-based apps)

Auto-instrumentation for `HttpClient`, `SqlClient`, and `ASP.NET` is available via:
- `OpenTelemetry.Instrumentation.Http` (supports .NET Framework)
- `OpenTelemetry.Instrumentation.SqlClient` (supports .NET Framework)
- `OpenTelemetry.Instrumentation.AspNet` (supports .NET Framework 4.x with an HttpModule)

## Step-by-step setup

### Step 1: Install NuGet packages

```powershell
Install-Package OpenTelemetry -Version 1.9.*
Install-Package OpenTelemetry.Exporter.OpenTelemetryProtocol -Version 1.9.*
Install-Package OpenTelemetry.Instrumentation.Http -Version 1.9.*
Install-Package OpenTelemetry.Instrumentation.SqlClient -Version 1.9.*
# For ASP.NET WebForms / MVC:
Install-Package OpenTelemetry.Instrumentation.AspNet -Version 1.9.*
```

### Step 2: Add the ASP.NET HttpModule (WebForms / MVC only)

In `Web.config`, add the `TelemetryHttpModule` to capture incoming HTTP request spans automatically:

```xml
<configuration>
  <system.webServer>
    <modules>
      <add name="TelemetryHttpModule"
           type="OpenTelemetry.Instrumentation.AspNet.TelemetryHttpModule,
                 OpenTelemetry.Instrumentation.AspNet"
           preCondition="managedHandler" />
    </modules>
  </system.webServer>
</configuration>
```

### Step 3: Initialize TracerProvider at startup

**For ASP.NET WebForms/MVC — in `Global.asax.cs`:**

```csharp
using OpenTelemetry;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

public class MvcApplication : System.Web.HttpApplication
{
    private static TracerProvider _tracerProvider;

    protected void Application_Start()
    {
        _tracerProvider = Sdk.CreateTracerProviderBuilder()
            .SetResourceBuilder(ResourceBuilder.CreateDefault()
                .AddService(
                    serviceName:    "my-webforms-app",
                    serviceVersion: "1.0.0"))
            .AddAspNetInstrumentation()
            .AddHttpClientInstrumentation()
            .AddSqlClientInstrumentation(opt => opt.SetDbStatementForText = true)
            .AddSource("my-webforms-app")   // custom spans
            .AddOtlpExporter(opt => {
                opt.Endpoint = new Uri(
                    Environment.GetEnvironmentVariable("ELASTIC_OTLP_ENDPOINT")
                    ?? "https://<deployment>.apm.<region>.cloud.es.io");
                opt.Headers =
                    $"Authorization=ApiKey {Environment.GetEnvironmentVariable("ELASTIC_API_KEY")}";
            })
            .Build();

        // ... rest of Application_Start ...
    }

    protected void Application_End()
    {
        _tracerProvider?.Dispose();
    }
}
```

**For a Windows Service — in `OnStart()`:**

```csharp
using OpenTelemetry;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

public class PaymentProcessorService : ServiceBase
{
    private static TracerProvider _tracerProvider;

    protected override void OnStart(string[] args)
    {
        _tracerProvider = Sdk.CreateTracerProviderBuilder()
            .SetResourceBuilder(ResourceBuilder.CreateDefault()
                .AddService("payment-processor-service"))
            .AddHttpClientInstrumentation()
            .AddSqlClientInstrumentation()
            .AddSource("payment-processor")
            .AddOtlpExporter(opt => {
                opt.Endpoint = new Uri(Environment.GetEnvironmentVariable("ELASTIC_OTLP_ENDPOINT"));
                opt.Headers  = $"Authorization=ApiKey {Environment.GetEnvironmentVariable("ELASTIC_API_KEY")}";
            })
            .Build();
    }

    protected override void OnStop()
    {
        _tracerProvider?.Dispose();
    }
}
```

### Step 4: Wrap business entry points with custom spans

Auto-instrumentation covers HTTP requests and SQL queries. For business logic (the actual domain actions your app performs), add custom spans manually.

### Step 5: Set environment variables

```bat
SET ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io
SET ELASTIC_API_KEY=<your-base64-encoded-id:key>
SET OTEL_DEPLOYMENT_ENVIRONMENT=production
```

## Code example

### Wrapping a WebForms code-behind with business spans

```csharp
using System;
using System.Diagnostics;
using OpenTelemetry.Trace;

public partial class CheckoutPage : System.Web.UI.Page
{
    // One ActivitySource per class or module — reuse across requests
    private static readonly ActivitySource _tracer =
        new ActivitySource("my-webforms-app");

    protected void btnSubmit_Click(object sender, EventArgs e)
    {
        var orderId    = Guid.NewGuid().ToString();
        var customerId = (string)Session["customer_id"];
        decimal total  = CalculateOrderTotal();

        using var span = _tracer.StartActivity("checkout.order_submitted");
        span?.SetTag("order.id",          orderId);
        span?.SetTag("order.value_usd",   (double)total);
        span?.SetTag("customer.id",       customerId);
        span?.SetTag("payment.method",    ddlPaymentMethod.SelectedValue);
        span?.SetTag("order.item_count",  CartItems.Count);

        try
        {
            var result = OrderService.SubmitOrder(orderId, customerId, CartItems, total);

            span?.SetTag("order.status",      result.Status);
            span?.SetTag("fulfillment.warehouse", result.WarehouseCode);

            Response.Redirect($"/order-confirmation.aspx?id={orderId}");
        }
        catch (Exception ex)
        {
            span?.RecordException(ex);
            span?.SetStatus(ActivityStatusCode.Error, ex.Message);
            // handle error...
            throw;
        }
    }
}
```

### Wrapping a WCF service operation

```csharp
using System.Diagnostics;
using System.ServiceModel;

[ServiceContract]
public interface IPaymentService
{
    [OperationContract]
    PaymentResult AuthorizePayment(PaymentRequest request);
}

public class PaymentService : IPaymentService
{
    private static readonly ActivitySource _tracer =
        new ActivitySource("payment-processor");

    public PaymentResult AuthorizePayment(PaymentRequest request)
    {
        using var span = _tracer.StartActivity("payment.authorize");
        span?.SetTag("payment.amount",      request.AmountCents / 100.0);
        span?.SetTag("payment.currency",    request.Currency);
        span?.SetTag("payment.method",      request.Method);
        span?.SetTag("customer.id",         request.CustomerId);
        span?.SetTag("merchant.id",         request.MerchantId);

        try
        {
            var result = _paymentGateway.Authorize(request);

            span?.SetTag("payment.charge_id",       result.ChargeId);
            span?.SetTag("payment.status",          result.Status);
            span?.SetTag("fraud.score",             result.FraudScore);
            span?.SetTag("fraud.decision",          result.FraudDecision);

            if (result.Status == "declined")
            {
                span?.SetTag("payment.decline_code",  result.DeclineCode);
                span?.SetStatus(ActivityStatusCode.Error, "Payment declined");
            }

            return result;
        }
        catch (Exception ex)
        {
            span?.RecordException(ex);
            span?.SetStatus(ActivityStatusCode.Error, ex.Message);
            throw;
        }
    }
}
```

### Wrapping a Windows Service background processor

```csharp
using System.Diagnostics;
using System.Threading;

public class OrderProcessor
{
    private static readonly ActivitySource _tracer =
        new ActivitySource("payment-processor");

    public void ProcessPendingOrders(CancellationToken ct)
    {
        var orders = _orderRepository.GetPendingOrders();

        foreach (var order in orders)
        {
            if (ct.IsCancellationRequested) break;

            using var span = _tracer.StartActivity("order.process");
            span?.SetTag("order.id",        order.Id);
            span?.SetTag("order.value_usd", order.TotalUsd);
            span?.SetTag("customer.tier",   order.CustomerTier);

            try
            {
                _fulfillmentService.Fulfill(order);
                span?.SetTag("order.status",   "fulfilled");
                span?.SetTag("warehouse.code", order.AssignedWarehouse);
            }
            catch (Exception ex)
            {
                span?.RecordException(ex);
                span?.SetStatus(ActivityStatusCode.Error, ex.Message);
                span?.SetTag("order.status", "failed");
                span?.SetTag("error.category", ClassifyError(ex));
            }
        }
    }
}
```

### MVC 5 controller action with business spans

```csharp
using System.Diagnostics;
using System.Web.Mvc;

public class InvoiceController : Controller
{
    private static readonly ActivitySource _tracer =
        new ActivitySource("my-webforms-app");

    [HttpPost]
    [ValidateAntiForgeryToken]
    public ActionResult Generate(InvoiceRequest model)
    {
        if (!ModelState.IsValid)
            return View(model);

        using var span = _tracer.StartActivity("invoice.generate");
        span?.SetTag("customer.id",      model.CustomerId);
        span?.SetTag("invoice.amount",   model.Amount);
        span?.SetTag("invoice.currency", model.Currency);
        span?.SetTag("invoice.type",     model.Type);

        try
        {
            var invoice = _invoiceService.Generate(model);
            span?.SetTag("invoice.id",     invoice.Id);
            span?.SetTag("invoice.status", "generated");

            return RedirectToAction("Details", new { id = invoice.Id });
        }
        catch (Exception ex)
        {
            span?.RecordException(ex);
            span?.SetStatus(ActivityStatusCode.Error, ex.Message);
            ModelState.AddModelError("", "Invoice generation failed.");
            return View(model);
        }
    }
}
```

### Environment variable configuration for IIS (web.config)

```xml
<configuration>
  <appSettings>
    <!-- Reference environment variables set at the OS level or IIS site level -->
  </appSettings>
  <system.webServer>
    <modules>
      <add name="TelemetryHttpModule"
           type="OpenTelemetry.Instrumentation.AspNet.TelemetryHttpModule,
                 OpenTelemetry.Instrumentation.AspNet"
           preCondition="managedHandler" />
    </modules>
  </system.webServer>
</configuration>
```

Set environment variables at the IIS site level (IIS Manager → Site → Configuration Editor → system.webServer/aspNetCore, or via ApplicationHost.config `environmentVariables` for in-process hosting).

## What you'll see in Elastic

Once the TracerProvider is initialized and spans are instrumented:

- **Named service** in Kibana APM (e.g., `my-webforms-app`) with all your WebForms or MVC operations.
- **Auto-instrumented spans**: Every SQL query via ADO.NET/SqlClient and every outbound HTTP call via `HttpClient` appears automatically as a child span with the SQL statement and URL captured.
- **Custom business spans**: `checkout.order_submitted`, `payment.authorize`, `invoice.generate` with your business attributes attached.
- **End-to-end traces**: An incoming WebForms request → business logic span → SQL query spans → outbound HTTP call to payment gateway — all stitched together as a single trace in Kibana.
- **Error analysis**: Exceptions are captured with full stack trace and error type, not just an HTTP 500 status.

Example ES|QL query to analyze payment authorizations:

```esql
FROM traces-apm*
| WHERE service.name == "my-webforms-app"
  AND span.name == "payment.authorize"
| STATS
    total          = COUNT(*),
    declined       = COUNT_IF(attributes.payment\.status == "declined"),
    avg_fraud_score = AVG(TO_DOUBLE(attributes.fraud\.score))
  BY bin(@timestamp, 1h)
| EVAL decline_rate = declined / total * 100
| SORT @timestamp DESC
```

## Related

- [OpenTelemetry for Legacy Runtimes — overview](./opentelemetry-legacy-runtimes.md)
- [Business Span Enrichment](./business-span-enrichment.md)
- [OpenTelemetry for Classic ASP / VBScript](./opentelemetry-classic-asp-vbscript.md)
- [Telemetry Sidecar Pattern](./telemetry-sidecar-pattern.md) (for components where SDK integration is not possible)
- [Elastic EDOT .NET documentation](https://www.elastic.co/docs/reference/opentelemetry)

---

> Found this useful? [Star the repo](https://github.com/gmoskovicz/edot-autopilot) — it helps other .NET Framework developers find this solution.
