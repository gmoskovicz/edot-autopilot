// Inventory Service — ASP.NET Core Minimal Hosting
//
// No observability. Run `Observe this project.` to add OpenTelemetry.

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddControllers();

var app = builder.Build();

app.MapControllers();

app.Run();
