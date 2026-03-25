/*
 * Tier B — .NET Framework 4.8 Manual OTel Wrapping
 *
 * EDOT only supports .NET 6+. For .NET Framework 4.x we manually wrap
 * entry points with OTel SDK spans — the language is supported, the framework is not.
 *
 * This simulates a legacy .NET Framework 4.8 web service (WebForms / ASMX-era).
 * Run: dotnet run
 */

using System;
using System.Collections.Generic;
using OpenTelemetry;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;
using OpenTelemetry.Exporter;

class Program
{
    static readonly ActivitySource Source = new("legacy-dotnet-framework");

    static void Main(string[] args)
    {
        // Bootstrap OTel manually (no EDOT agent available for .NET Framework)
        var endpoint = Environment.GetEnvironmentVariable("ELASTIC_OTLP_ENDPOINT") ?? "";
        var apiKey   = Environment.GetEnvironmentVariable("ELASTIC_API_KEY") ?? "";
        var svcName  = Environment.GetEnvironmentVariable("OTEL_SERVICE_NAME") ?? "dotnet-framework-tier-b";

        using var tracerProvider = Sdk.CreateTracerProviderBuilder()
            .SetResourceBuilder(ResourceBuilder.CreateDefault()
                .AddService(svcName, serviceVersion: "1.0.0")
                .AddAttributes(new Dictionary<string, object> {
                    ["deployment.environment"] = Environment.GetEnvironmentVariable("OTEL_DEPLOYMENT_ENVIRONMENT") ?? "development"
                }))
            .AddSource("legacy-dotnet-framework")
            .AddOtlpExporter(opt => {
                opt.Endpoint = new Uri($"{endpoint.TrimEnd('/')}/v1/traces");
                opt.Headers  = $"Authorization=ApiKey {apiKey}";
                opt.Protocol = OtlpExportProtocol.HttpProtobuf;
            })
            .Build();

        Console.WriteLine($"[edot-dotnet-framework-tier-b] Sending test spans to Elastic...");

        // Simulate processing three orders
        SimulateOrderProcessing("ORD-001", 1250.00, "pro");
        SimulateOrderProcessing("ORD-002", 4200.00, "enterprise");
        SimulateOrderProcessing("ORD-003", 29.99, "free");

        Console.WriteLine("Done. Check Kibana → APM → Services → dotnet-framework-tier-b");
    }

    /// <summary>
    /// Tier B pattern: manually wrap the legacy entry point in an OTel span.
    /// The original business logic is unchanged — we just add the span around it.
    /// </summary>
    static void SimulateOrderProcessing(string orderId, double amount, string customerTier)
    {
        using var activity = Source.StartActivity("order.process");
        if (activity == null) return;

        // Phase 3: business enrichment
        activity.SetTag("order.id",          orderId);
        activity.SetTag("order.value_usd",   amount);
        activity.SetTag("customer.tier",     customerTier);

        try
        {
            // Simulate fraud check (legacy business logic — unchanged)
            var fraudScore = new Random().NextDouble();
            activity.SetTag("fraud.score",    Math.Round(fraudScore, 3));

            if (fraudScore > 0.85)
            {
                activity.SetTag("fraud.decision",  "blocked");
                activity.SetStatus(ActivityStatusCode.Error, "Order blocked by fraud check");
                Console.WriteLine($"  [BLOCKED] {orderId} fraud_score={fraudScore:F2}");
                return;
            }

            activity.SetTag("fraud.decision", "approved");
            activity.SetTag("order.status",   "confirmed");
            Console.WriteLine($"  [OK]      {orderId} amount=${amount} tier={customerTier}");
        }
        catch (Exception ex)
        {
            activity.RecordException(ex);
            activity.SetStatus(ActivityStatusCode.Error, ex.Message);
            throw;
        }
    }
}
