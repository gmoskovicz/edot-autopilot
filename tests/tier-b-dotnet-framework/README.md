# Tier B — .NET Framework Manual OTel Wrapping

EDOT supports .NET 6+ only. For .NET Framework 4.x (WebForms, WCF, classic ASP.NET MVC), the OTel SDK is available but the EDOT auto-agent doesn't work.

**Strategy:** Manually wrap entry points using `ActivitySource` spans. The original business logic is untouched — spans are added around it.

This is the difference between:
- ❌ `POST /api/order` — HTTP status 200, duration 340ms *(what auto-instrumentation gives you)*
- ✅ `order.process` — `order.value_usd=4200`, `customer.tier=enterprise`, `fraud.score=0.23` *(what manual wrapping + Phase 3 gives you)*

## Run

```bash
export ELASTIC_OTLP_ENDPOINT=https://YOUR-DEPLOYMENT.ingest.REGION.gcp.elastic.cloud:443
export ELASTIC_API_KEY=YOUR-BASE64-API-KEY
export OTEL_SERVICE_NAME=dotnet-framework-tier-b

dotnet run
```

## The pattern

```csharp
// Tier B wrapping pattern — apply to every legacy entry point
using var activity = Source.StartActivity("business.action.name");
activity?.SetTag("order.value_usd", amount);
activity?.SetTag("customer.tier", tier);
try {
    // original business logic unchanged
} catch (Exception ex) {
    activity?.RecordException(ex);
    activity?.SetStatus(ActivityStatusCode.Error, ex.Message);
    throw;
}
```

## Verify in Elastic

Kibana → Observability → APM → Services → `dotnet-framework-tier-b`
