// Smoke test: Tier A — .NET C# (native OTel SDK, full O11y: traces + logs + metrics).
//
// Business scenario: inventory management microservice — receive stock transfer
// request, validate locations, update quantities, emit domain event.
//
// Run (requires .NET 8+ SDK):
//   cd smoke-tests/11-tier-a-dotnet && dotnet run
//
// Or via the Python runner:
//   cd smoke-tests && python3 11-tier-a-dotnet/smoke.py

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Diagnostics.Metrics;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using OpenTelemetry;
using OpenTelemetry.Exporter;
using OpenTelemetry.Metrics;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

const string SvcName = "smoke-tier-a-dotnet";

// Load .env
var envPath = Path.Combine(AppContext.BaseDirectory, "../../.env");
if (File.Exists(envPath))
{
    foreach (var line in File.ReadAllLines(envPath))
    {
        var trimmed = line.Trim();
        if (string.IsNullOrEmpty(trimmed) || trimmed.StartsWith("#") || !trimmed.Contains('='))
            continue;
        var idx = trimmed.IndexOf('=');
        var key = trimmed[..idx];
        var val = trimmed[(idx + 1)..];
        if (Environment.GetEnvironmentVariable(key) == null)
            Environment.SetEnvironmentVariable(key, val);
    }
}

var endpoint = Environment.GetEnvironmentVariable("ELASTIC_OTLP_ENDPOINT") ?? "";
var apiKey   = Environment.GetEnvironmentVariable("ELASTIC_API_KEY") ?? "";
var envName  = Environment.GetEnvironmentVariable("OTEL_DEPLOYMENT_ENVIRONMENT") ?? "smoke-test";
var authHeader = new Dictionary<string, string> { ["Authorization"] = $"ApiKey {apiKey}" };

var resourceBuilder = ResourceBuilder.CreateDefault()
    .AddService(SvcName)
    .AddAttributes(new[] { new KeyValuePair<string, object>("deployment.environment", envName) });

using var tracerProvider = Sdk.CreateTracerProviderBuilder()
    .SetResourceBuilder(resourceBuilder)
    .AddSource(SvcName)
    .AddOtlpExporter(o => {
        o.Endpoint = new Uri($"{endpoint}/v1/traces");
        o.Headers  = $"Authorization=ApiKey {apiKey}";
        o.Protocol = OtlpExportProtocol.HttpProtobuf;
    })
    .Build()!;

using var meterProvider = Sdk.CreateMeterProviderBuilder()
    .SetResourceBuilder(resourceBuilder)
    .AddMeter(SvcName)
    .AddOtlpExporter(o => {
        o.Endpoint = new Uri($"{endpoint}/v1/metrics");
        o.Headers  = $"Authorization=ApiKey {apiKey}";
        o.Protocol = OtlpExportProtocol.HttpProtobuf;
    })
    .Build()!;

var activitySource = new ActivitySource(SvcName);
var meter          = new Meter(SvcName);
var transferCount  = meter.CreateCounter<long>("inventory.transfers");
var quantityHist   = meter.CreateHistogram<double>("inventory.transfer_qty");
var durationHist   = meter.CreateHistogram<double>("inventory.transfer_ms", unit: "ms");

record StockTransfer(string Id, string FromLoc, string ToLoc, string Sku, int Qty, string RequestedBy);

var transfers = new[]
{
    new StockTransfer("TRF-0001", "WH-EAST-A1", "WH-WEST-B3", "SKU-8811", 500,  "system.rebalancer"),
    new StockTransfer("TRF-0002", "WH-WEST-C2", "STORE-NYC-01","SKU-4423", 50,   "ops.manual"),
    new StockTransfer("TRF-0003", "WH-EAST-B2", "WH-SOUTH-D1","SKU-9912", 1200, "system.rebalancer"),
    new StockTransfer("TRF-0004", "STORE-LA-03","WH-EAST-A1",  "SKU-1156", 12,   "ops.manual"),
};

Console.WriteLine($"\n[{SvcName}] Processing inventory transfers via native .NET OTel SDK...");

foreach (var xfer in transfers)
{
    var sw = Stopwatch.StartNew();
    using var activity = activitySource.StartActivity("inventory.process_transfer",
        ActivityKind.Server,
        parentContext: default,
        tags: new[]
        {
            new KeyValuePair<string, object?>("transfer.id",      xfer.Id),
            new KeyValuePair<string, object?>("transfer.from",    xfer.FromLoc),
            new KeyValuePair<string, object?>("transfer.to",      xfer.ToLoc),
            new KeyValuePair<string, object?>("inventory.sku",    xfer.Sku),
            new KeyValuePair<string, object?>("inventory.qty",    xfer.Qty),
            new KeyValuePair<string, object?>("transfer.requester", xfer.RequestedBy),
        });

    // Validate locations
    using (var va = activitySource.StartActivity("inventory.validate_locations", ActivityKind.Internal))
    {
        Thread.Sleep(Random.Shared.Next(5, 20));
        va?.SetTag("validation.from_valid", true);
        va?.SetTag("validation.to_valid",   true);
    }

    // Check available stock
    using (var sa = activitySource.StartActivity("inventory.check_stock", ActivityKind.Client))
    {
        sa?.SetTag("db.system", "sqlserver");
        sa?.SetTag("db.operation", "SELECT");
        Thread.Sleep(Random.Shared.Next(10, 40));
        sa?.SetTag("inventory.available_qty", xfer.Qty + Random.Shared.Next(0, 200));
    }

    // Commit transfer
    using (var ca = activitySource.StartActivity("inventory.commit_transfer", ActivityKind.Client))
    {
        ca?.SetTag("db.system", "sqlserver");
        ca?.SetTag("db.operation", "UPDATE");
        Thread.Sleep(Random.Shared.Next(15, 50));
        ca?.SetTag("db.rows_affected", 2);
    }

    // Emit domain event
    using (var ea = activitySource.StartActivity("events.publish_stock_transferred", ActivityKind.Producer))
    {
        ea?.SetTag("messaging.system", "servicebus");
        ea?.SetTag("event.type", "StockTransferred");
        Thread.Sleep(Random.Shared.Next(5, 25));
    }

    sw.Stop();
    activity?.SetTag("transfer.duration_ms", sw.ElapsedMilliseconds);
    activity?.SetStatus(ActivityStatusCode.Ok);

    var tags = new TagList
    {
        { "transfer.direction", xfer.FromLoc.StartsWith("WH") && xfer.ToLoc.StartsWith("STORE") ? "wh-to-store" : "wh-to-wh" },
    };
    transferCount.Add(1, tags);
    quantityHist.Record(xfer.Qty, tags);
    durationHist.Record(sw.Elapsed.TotalMilliseconds, tags);

    Console.WriteLine($"  ✅ {xfer.Id}  {xfer.FromLoc,-14} → {xfer.ToLoc,-14}  sku={xfer.Sku}  qty={xfer.Qty,5}  dur={sw.ElapsedMilliseconds}ms");
}

tracerProvider.ForceFlush();
meterProvider.ForceFlush();
Console.WriteLine($"[{SvcName}] Done → Kibana APM → {SvcName}");
