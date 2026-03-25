using Microsoft.AspNetCore.Mvc;

namespace InventoryService.Controllers;

/// <summary>
/// Inventory Transfer REST API — ASP.NET Core
///
/// No observability. Run `Observe this project.` to add OpenTelemetry.
/// </summary>
[ApiController]
[Route("[controller]")]
public class InventoryController : ControllerBase
{
    private static readonly Dictionary<string, TransferRecord> Transfers = new();

    private readonly ILogger<InventoryController> _logger;

    public InventoryController(ILogger<InventoryController> logger)
    {
        _logger = logger;
    }

    [HttpGet("/health")]
    public IActionResult Health() => Ok(new { status = "ok" });

    [HttpGet("/inventory/{sku}")]
    public IActionResult GetStock(string sku)
    {
        var qty = new Random().Next(0, 500);
        return Ok(new { sku, quantity = qty, warehouse = "WH-EAST-A1" });
    }

    [HttpPost("/transfers")]
    public async Task<IActionResult> CreateTransfer([FromBody] TransferRequest req)
    {
        if (req.Quantity <= 0)
            return BadRequest(new { error = "quantity must be > 0" });

        if (string.IsNullOrEmpty(req.FromLocation) || string.IsNullOrEmpty(req.ToLocation))
            return BadRequest(new { error = "from_location and to_location required" });

        // Simulate DB stock check
        await Task.Delay(Random.Shared.Next(10, 40));
        var availableQty = Random.Shared.Next(req.Quantity, req.Quantity + 500);

        if (availableQty < req.Quantity)
            return UnprocessableEntity(new { error = "insufficient stock", available = availableQty });

        // Simulate DB commit
        await Task.Delay(Random.Shared.Next(15, 50));

        var transferId = $"TRF-{Guid.NewGuid():N}"[..10].ToUpper();
        var record = new TransferRecord
        {
            TransferId    = transferId,
            Sku           = req.Sku,
            Quantity      = req.Quantity,
            FromLocation  = req.FromLocation,
            ToLocation    = req.ToLocation,
            Requester     = req.Requester ?? "system",
            Status        = "completed",
            CompletedAt   = DateTime.UtcNow,
        };
        Transfers[transferId] = record;

        _logger.LogInformation(
            "Transfer {TransferId} completed: {Qty}x {Sku} from {From} to {To}",
            transferId, req.Quantity, req.Sku, req.FromLocation, req.ToLocation);

        return StatusCode(201, record);
    }

    [HttpGet("/transfers/{id}")]
    public IActionResult GetTransfer(string id)
    {
        if (!Transfers.TryGetValue(id, out var record))
            return NotFound(new { error = "not found" });
        return Ok(record);
    }
}

public record TransferRequest(
    string  Sku,
    int     Quantity,
    string  FromLocation,
    string  ToLocation,
    string? Requester = null
);

public record TransferRecord
{
    public string   TransferId   { get; init; } = "";
    public string   Sku          { get; init; } = "";
    public int      Quantity     { get; init; }
    public string   FromLocation { get; init; } = "";
    public string   ToLocation   { get; init; } = "";
    public string   Requester    { get; init; } = "";
    public string   Status       { get; init; } = "";
    public DateTime CompletedAt  { get; init; }
}
